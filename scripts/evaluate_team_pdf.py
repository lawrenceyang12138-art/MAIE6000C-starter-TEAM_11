"""Evaluate frozen team answers using the real scan, PDF parser, and search index.

This operator tool runs existing handlers synchronously. It does not substitute
hand-authored chunks or claim to exercise the API/worker dispatcher. Original
fixtures and frozen answers are read only; a staged corpus contains exact copies
of the files selected by the frozen manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path, PurePosixPath

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.common.config import Settings, get_settings
from services.common.db import Base, make_engine, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
    SourceChunk,
    VersionStatus,
    utcnow,
)
from services.parsing.chunking import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS, MIN_CHUNK_CHARS
from services.parsing.handler import PARSER_REVISION, handle_extract_file
from services.scan.handler import handle_scan_root, resolve_source_path
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    HTTPEmbeddingBackend,
    LocalPplxEmbeddingBackend,
)
from services.search.evaluation import evaluate_queries
from services.search.indexing import embed_version
from services.search.page_metadata import VersionPageMetadata, load_page_metadata
from services.search.navigation_runtime import NAVIGATION_PROFILE, PLAIN_PROFILE
from services.search.text import (
    MAX_BATCH_SIZE,
    MAX_DOCUMENT_MODEL_TOKENS,
    MAX_QUERY_MODEL_TOKENS,
    MAX_QUERY_TOKENS,
    MAX_TEXT_CHARS,
    MODEL_ID,
    MODEL_DIRECTORY,
    MODEL_FORWARD_BATCH_SIZE,
    MODEL_REVISION,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    TOKEN_DIMENSIONS,
)
from services.search.token_store import (
    ChunkTokenIndex,
    index_matches_text,
    prepare_search_schema,
)

REPO = Path(__file__).resolve().parents[1]


class CorpusValidationError(ValueError):
    def __init__(self, diagnostics: list[dict]) -> None:
        super().__init__("Frozen corpus or answer validation failed")
        self.diagnostics = diagnostics


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_path(base: Path, relative_path: str) -> Path:
    value = PurePosixPath(relative_path.replace("\\", "/"))
    if value.is_absolute() or ".." in value.parts or ":" in relative_path or not value.parts:
        raise CorpusValidationError([
            {"code": "path_out_of_scope", "relative_path": relative_path}
        ])
    result = (base / value).resolve()
    if not result.is_relative_to(base.resolve()):
        raise CorpusValidationError([
            {"code": "path_out_of_scope", "relative_path": relative_path}
        ])
    return result


def validate_corpus(corpus_dir: Path, manifest: dict, *, exact: bool = True) -> list[dict]:
    """Check relative identity and every byte hash, including unsupported files."""
    corpus_dir = corpus_dir.resolve()
    diagnostics = []
    observed = []
    expected_paths = [record["relative_path"] for record in manifest["files"]]
    if len(expected_paths) != len(set(expected_paths)):
        raise CorpusValidationError([{"code": "duplicate_manifest_path"}])
    for record in manifest["files"]:
        source = _source_path(corpus_dir, record["relative_path"])
        if not source.is_file():
            diagnostics.append({
                "code": "corpus_file_missing", "relative_path": record["relative_path"]
            })
            continue
        actual = digest(source)
        observed.append({
            "relative_path": record["relative_path"],
            "sha256": actual,
            "byte_size": source.stat().st_size,
            "matches_frozen_manifest": actual == record["sha256"],
        })
        if actual != record["sha256"]:
            diagnostics.append({
                "code": "corpus_content_mismatch",
                "relative_path": record["relative_path"],
                "expected_sha256": record["sha256"],
                "actual_sha256": actual,
            })
    if exact and corpus_dir.is_dir():
        actual_paths = {
            item.relative_to(corpus_dir).as_posix()
            for item in corpus_dir.rglob("*") if item.is_file()
        }
        extras = sorted(actual_paths - set(expected_paths))
        if extras:
            diagnostics.append({"code": "corpus_unexpected_files", "relative_paths": extras})
        links = [item.relative_to(corpus_dir).as_posix()
                 for item in corpus_dir.rglob("*") if item.is_symlink()]
        if links:
            diagnostics.append({"code": "corpus_symlinks_not_allowed", "relative_paths": links})
    if diagnostics:
        raise CorpusValidationError(diagnostics)
    return observed


def stage_corpus(source_dir: Path, destination: Path, manifest: dict) -> list[dict]:
    """Copy only manifest files, preserving bytes and refusing unrelated overwrite."""
    source_dir, destination = source_dir.resolve(), destination.resolve()
    if destination.is_relative_to(source_dir) or source_dir.is_relative_to(destination):
        raise CorpusValidationError([{"code": "corpus_stage_overlaps_source"}])
    validate_corpus(source_dir, manifest, exact=False)
    if destination.exists():
        return validate_corpus(destination, manifest)
    destination.mkdir(parents=True)
    for record in manifest["files"]:
        source = _source_path(source_dir, record["relative_path"])
        target = _source_path(destination, record["relative_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return validate_corpus(destination, manifest)


@contextmanager
def source_mounts(settings: Settings):
    """Give the existing scan resolver an explicit process-local allowlist."""
    previous = os.environ.get("SOURCE_MOUNTS")
    os.environ["SOURCE_MOUNTS"] = json.dumps(settings.source_mounts)
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SOURCE_MOUNTS", None)
        else:
            os.environ["SOURCE_MOUNTS"] = previous
        get_settings.cache_clear()


class _DisabledBackend:
    model_id, dimensions = MODEL_ID, TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        raise EmbeddingUnavailable("ai_disabled")


def evaluate_corpus(
    db: Session,
    corpus_dir: Path,
    gold: dict,
    manifest: dict,
    settings: Settings,
    backend: EmbeddingBackend | None,
) -> dict:
    """Run production handlers over an exact, already validated source tree."""
    corpus_dir = corpus_dir.resolve()
    before = validate_corpus(corpus_dir, manifest)
    mount_id = "c-eval-" + hashlib.sha256(str(corpus_dir).encode()).hexdigest()[:12]
    scoped = settings.model_copy(update={"source_mounts": {mount_id: str(corpus_dir)}})
    with source_mounts(scoped):
        root = db.scalar(select(AuthorizedRoot).where(
            AuthorizedRoot.mount_id == mount_id, AuthorizedRoot.relative_path == "."
        ))
        if root is None:
            root = AuthorizedRoot(
                mount_id=mount_id, relative_path=".", status=RootStatus.ACTIVE.value
            )
            db.add(root)
            db.commit()
        if root.status != RootStatus.ACTIVE.value:
            raise CorpusValidationError([{"code": "root_not_active", "root_id": root.id}])
        scan = handle_scan_root(db, root.id)
        files = list(db.scalars(select(FileRecord).where(
            FileRecord.root_id == root.id
        ).order_by(FileRecord.relative_path)))
        expected_paths = {item["relative_path"] for item in manifest["files"]}
        database_paths = {item.relative_path for item in files}
        if database_paths != expected_paths:
            raise CorpusValidationError([{
                "code": "database_corpus_mismatch",
                "extra_relative_paths": sorted(database_paths - expected_paths),
                "missing_relative_paths": sorted(expected_paths - database_paths),
            }])
        processing = []
        for record in files:
            version = db.get(FileVersion, record.current_version_id)
            if version is None:
                processing.append({
                    "file_id": record.id, "relative_path": record.relative_path,
                    "status": "current_version_missing", "error_code": "no_current_version",
                    "index": None,
                })
                continue
            job = db.scalar(select(Job).where(
                Job.version_id == version.id,
                Job.job_type == RootJobType.EXTRACT_FILE.value,
                Job.status == JobStatus.PENDING.value,
            ).order_by(Job.id))
            if job is not None:
                job.status, job.claimed_at = JobStatus.CLAIMED.value, utcnow()
                job.attempts += 1
                db.commit()
            # Re-parse even a ready version: existing database rows alone do
            # not prove that their chunks were produced from these PDF bytes.
            # B preserves IDs for unchanged source text/page/ordinal.
            handle_extract_file(db, version.id, resolve_source_path(db, version.id))
            if job is not None:
                job.status, job.completed_at = JobStatus.COMPLETED.value, utcnow()
                db.commit()
            indexed = None
            if version.status in {VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value}:
                indexed = asdict(embed_version(db, version.id, backend or _DisabledBackend()))
                db.commit()
            processing.append({
                "file_id": record.id,
                "version_id": version.id,
                "relative_path": record.relative_path,
                "content_sha256": version.content_sha256,
                "status": version.status,
                "error_code": version.error_code,
                "parser_revision": version.parser_revision,
                "parsed_this_run": True,
                "index": indexed,
            })
        frozen_by_path = {item["relative_path"]: item for item in manifest["files"]}
        classification_differences = []
        for actual in processing:
            frozen = frozen_by_path[actual["relative_path"]]
            if (actual["status"] != frozen["expected_status"]
                    or actual["error_code"] != frozen.get("expected_error_code")):
                classification_differences.append({
                    "relative_path": actual["relative_path"],
                    "expected_status": frozen["expected_status"],
                    "actual_status": actual["status"],
                    "expected_error_code": frozen.get("expected_error_code"),
                    "actual_error_code": actual["error_code"],
                    "impact": "corpus_classification_handoff; retrieval_denominators_unchanged",
                })
        evaluation = evaluate_queries(
            db, gold, scoped, backend, manifest=manifest, root_id=root.id
        )
        disk_evidence = {}
        for query in evaluation["queries"]:
            for item in query["ranked_results"]:
                if item["chunk_id"] in disk_evidence:
                    continue
                checked = {
                    "chunk_id": item["chunk_id"], "version_id": item["version_id"],
                    "file_id": item["file_id"], "relative_path": item["file_path"],
                    "page": item["page"], "readable": False,
                }
                try:
                    path = resolve_source_path(db, item["version_id"], for_write=False)
                    actual_hash = digest(path)
                    checked["content_sha256"] = actual_hash
                    checked["readable"] = (
                        item["evidence_matches_result"]
                        and actual_hash == item["evidence"]["content_sha256"]
                    )
                    if not checked["readable"]:
                        checked["error_code"] = "source_identity_mismatch"
                except (OSError, ValueError, LookupError) as exc:
                    checked["error_code"] = "source_file_unavailable"
                    checked["exception_type"] = type(exc).__name__
                disk_evidence[item["chunk_id"]] = checked
        disk_failures = sum(not item["readable"] for item in disk_evidence.values())
        evaluation["on_disk_evidence"] = list(disk_evidence.values())
        evaluation["summary"]["on_disk_evidence_failures"] = disk_failures
        evaluation["passed"] = evaluation["passed"] and disk_failures == 0
        indexed_count = db.scalar(select(func.count()).select_from(ChunkSearchIndex).join(
            SourceChunk, SourceChunk.id == ChunkSearchIndex.chunk_id
        ).join(FileVersion, FileVersion.id == SourceChunk.version_id).join(
            FileRecord, FileRecord.id == FileVersion.file_id
        ).where(
            FileRecord.root_id == root.id,
            FileRecord.current_version_id == FileVersion.id,
        ))
        token_rows = list(db.execute(
            select(ChunkTokenIndex, SourceChunk)
            .join(SourceChunk, SourceChunk.id == ChunkTokenIndex.chunk_id)
            .join(FileVersion, FileVersion.id == SourceChunk.version_id)
            .join(FileRecord, FileRecord.id == FileVersion.file_id)
            .where(FileRecord.root_id == root.id,
                   FileRecord.current_version_id == FileVersion.id)
        ))
        compatible_token_rows = [
            index for index, chunk in token_rows if index_matches_text(index, chunk.text)
        ]
        pipeline = {
            "execution": "synchronous_existing_scan_parse_index_handlers",
            "worker_dispatcher": "not_exercised_by_this_runner",
            "root_id": root.id,
            "mount_id": mount_id,
            "source_mounts": scoped.source_mounts,
            "authorized_relative_path": ".",
            "scan": scan,
            "files": processing,
            "parsed_files_this_run": sum(item.get("parsed_this_run", False) for item in processing),
            "status_counts": dict(Counter(item["status"] for item in processing)),
            "frozen_classification_differences": classification_differences,
            "embedding_errors": dict(Counter(
                item["index"]["embedding_error"] for item in processing
                if item.get("index") and item["index"]["embedding_error"]
            )),
            "embedded_chunks_this_run": sum(
                item["index"]["embedded_count"] for item in processing if item.get("index")
            ),
            "search_index_chunks": indexed_count,
            "token_index_chunks": len(token_rows),
            "compatible_token_index_chunks": len(compatible_token_rows),
            "token_vector_count": sum(index.token_count for index in compatible_token_rows),
            "token_dimensions": TOKEN_DIMENSIONS,
            "parser_revision": PARSER_REVISION,
            "page_metadata": [
                {
                    "version_id": item["version_id"],
                    "page_count": item["index"].get("page_count"),
                    "error": item["index"].get("page_metadata_error"),
                }
                for item in processing if item.get("index")
            ],
            "ready_page_metadata_versions": sum(
                load_page_metadata(db, db.get(FileVersion, item["version_id"]))[1] == "ready"
                for item in processing if item.get("index")
            ),
        }
    after = validate_corpus(corpus_dir, manifest)
    evaluation["pipeline"] = pipeline
    evaluation["corpus_files"] = after
    evaluation["source_bytes_unchanged"] = before == after
    return evaluation


def git_state() -> dict:
    def git_bytes(*arguments: str) -> bytes:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=REPO, capture_output=True, check=False
            )
        except OSError:
            # Runtime images intentionally omit Git and repository metadata.
            # Source hashes still identify the evaluated implementation.
            return b"unavailable"
        return result.stdout.strip() if result.returncode == 0 else b"unavailable"

    def git(*arguments: str) -> str:
        # Git emits repository bytes, not the Windows console's GBK code page.
        # Replace undecodable display text only; the diff fingerprint stays exact.
        return git_bytes(*arguments).decode("utf-8", errors="replace")
    source_files = [
        *sorted((REPO / "services/search").glob("*.py")), Path(__file__),
        REPO / "scripts/search_tools.py", REPO / "scripts/verify_team_search_runtime.py",
        REPO / "services/ai/app/main.py", REPO / "services/common/config.py",
        REPO / "pyproject.toml", REPO / "compose.yaml", REPO / ".env.example",
    ]
    return {
        "sha": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "working_tree_status": git("status", "--porcelain", "--untracked-files=normal"),
        "tracked_diff_sha256": hashlib.sha256(git_bytes("diff", "--binary")).hexdigest(),
        "source_sha256": {
            path.relative_to(REPO).as_posix(): digest(path)
            for path in source_files if path.is_file()
        },
    }


def dependency_versions() -> dict:
    packages = {}
    for name in (
        "sqlalchemy", "pypdf", "psycopg", "pgvector", "fastapi", "httpx", "torch",
        "transformers", "sentence-transformers", "torchvision", "Pillow", "huggingface-hub",
    ):
        try:
            packages[name] = package_version(name)
        except PackageNotFoundError:
            packages[name] = "not_installed"
    return packages


def public_command(command_line: list[str]) -> list[str]:
    """Keep an executable command record without publishing database passwords."""
    result = list(command_line)
    for index, argument in enumerate(result):
        if argument == "--database-url" and index + 1 < len(result):
            result[index + 1] = make_url(result[index + 1]).render_as_string(hide_password=True)
        elif argument.startswith("--database-url="):
            result[index] = "--database-url=" + make_url(
                argument.split("=", 1)[1]
            ).render_as_string(hide_password=True)
    return result


def validate_report_destination(
    output: Path,
    *,
    protected_files: list[Path],
    source_directories: list[Path],
) -> None:
    """Refuse report paths that could overwrite answers or read-only source data.

    Resolve aliases and existing symlinks before comparing paths. Callers should
    surface this error without writing a failure report to the refused path.
    """
    destination = output.resolve()
    if any(destination == source.resolve() for source in protected_files):
        raise ValueError("output_path_conflict: report would overwrite a protected input")
    if any(destination.is_relative_to(source.resolve()) for source in source_directories):
        raise ValueError("output_path_inside_source: reports must be outside source directories")


def prepare_schema(engine, database_url: str) -> dict:
    """Use metadata for SQLite smoke tests, and real migrations for PostgreSQL.

    B's canonical migration chain currently uses PostgreSQL ALTER COLUMN syntax.
    Do not patch or stamp that chain here. A partial existing SQLite schema is an
    operator-visible failure, never something create_all should silently fill.
    """
    if engine.dialect.name != "sqlite":
        config = Config(str(REPO / "alembic.ini"))
        config.set_main_option("script_location", str(REPO / "alembic"))
        config.attributes["database_url"] = database_url
        command.upgrade(config, "head")
        prepare_search_schema(engine)
        return {
            "schema_source": "alembic_upgrade_head",
            "migration_validation": "upgrade_head_executed",
            "pg_only_migration_validation": True,
            "token_schema_source": "c_owned_prepare_search_schema",
        }
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = set(Base.metadata.tables) - {
        ChunkTokenIndex.__tablename__, VersionPageMetadata.__tablename__,
    }
    if not existing:
        Base.metadata.create_all(engine)
        action = "created_empty_database"
    else:
        missing_tables = sorted(expected - existing)
        missing_columns = {}
        for name in sorted(expected & existing):
            columns = {column["name"] for column in inspector.get_columns(name)}
            missing = sorted(set(Base.metadata.tables[name].columns.keys()) - columns)
            if missing:
                missing_columns[name] = missing
        if missing_tables or missing_columns:
            raise CorpusValidationError([{
                "code": "sqlite_schema_partial",
                "existing_tables": sorted(existing),
                "missing_tables": missing_tables,
                "missing_columns": missing_columns,
                "action": "refused_without_modifying_existing_schema",
                "remedy": "Use a new disposable SQLite database; PostgreSQL validates migrations",
            }])
        action = "validated_existing_metadata_schema"
    prepare_search_schema(engine)
    return {
        "schema_source": "sqlalchemy_metadata_sqlite_test_only",
        "schema_action": action,
        "migration_validation": "not_run_sqlite_migration_chain_requires_postgresql",
        "pg_only_migration_validation": False,
        "token_schema_source": "c_owned_prepare_search_schema",
        "limitation": "SQLite smoke tests do not verify PostgreSQL migrations or pgvector SQL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///work/team-pdf-evaluation.db")
    parser.add_argument("--corpus-dir", type=Path,
                        help="Existing exact manifest corpus; no staging when supplied")
    parser.add_argument("--fixture-root", type=Path, default=REPO / "fixtures")
    parser.add_argument("--stage-dir", type=Path, default=REPO / "work/team-pdf-corpus")
    parser.add_argument("--manifest", type=Path, default=REPO / "fixtures/manifest.json")
    parser.add_argument("--gold", type=Path, default=REPO / "submissions/week07/gold-queries.json")
    parser.add_argument("--freeze", type=Path,
                        default=REPO / "submissions/week07/gold-queries.freeze.json")
    parser.add_argument("--backend", choices=["local", "http", "off"], default="local")
    parser.add_argument("--page-navigation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--model-path", type=Path, default=REPO / MODEL_DIRECTORY)
    parser.add_argument("--ai-url", default="http://127.0.0.1:8100")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--keyword-weight", type=float, default=0.65)
    parser.add_argument("--semantic-weight", type=float, default=0.35)
    parser.add_argument("--candidate-limit", type=int, default=200)
    parser.add_argument("--output", type=Path, default=REPO / "work/team-pdf-evaluation.json")
    args = parser.parse_args()
    try:
        validate_report_destination(
            args.output,
            protected_files=[args.gold, args.manifest, args.freeze],
            source_directories=[
                args.fixture_root, args.stage_dir,
                *([args.corpus_dir] if args.corpus_dir is not None else []),
            ],
        )
    except ValueError as exc:
        parser.error(str(exc))
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "command": public_command([
            sys.executable, "-m", "scripts.evaluate_team_pdf", *sys.argv[1:]
        ]),
        "git": git_state(),
        "runtime": {"python": platform.python_version(), "packages": dependency_versions()},
        "database": {"url": make_url(args.database_url).render_as_string(hide_password=True)},
        "passed": False,
    }
    try:
        gold = json.loads(args.gold.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
        gold_hash, manifest_hash = digest(args.gold), digest(args.manifest)
        report["answer_version"] = {
            "schema_version": gold.get("schema_version"),
            "freeze": freeze,
            "gold_sha256": gold_hash,
            "manifest_sha256": manifest_hash,
            "freeze_sha256": digest(args.freeze),
            "human_B_review": gold.get("human_review", {}).get("status", "pending"),
        }
        checks = []
        if gold_hash != freeze["gold_sha256"]:
            checks.append({"code": "frozen_gold_hash_mismatch"})
        if manifest_hash != freeze["manifest_sha256"]:
            checks.append({"code": "frozen_manifest_hash_mismatch"})
        if checks:
            raise CorpusValidationError(checks)
        corpus_dir = args.corpus_dir or args.stage_dir
        if args.corpus_dir:
            validate_corpus(corpus_dir, manifest)
        else:
            stage_corpus(args.fixture_root, corpus_dir, manifest)
        settings = Settings(
            _env_file=None,
            embedding_enabled=args.backend != "off",
            embedding_cpu_threads=args.cpu_threads,
            search_request_timeout_seconds=args.timeout,
            search_keyword_weight=args.keyword_weight,
            search_semantic_weight=args.semantic_weight,
            search_max_candidates=args.candidate_limit,
            search_page_navigation_enabled=args.page_navigation,
        )
        backend = None
        if args.backend == "local":
            backend = LocalPplxEmbeddingBackend(str(args.model_path), args.cpu_threads)
        elif args.backend == "http":
            backend = HTTPEmbeddingBackend(args.ai_url, timeout=args.timeout)
        model_manifest = args.model_path / "model-manifest.json"
        report["configuration"] = {
            "backend": args.backend,
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "dimensions": TOKEN_DIMENSIONS,
            "representation": "token_multivector",
            "scoring": "maxsim_mean",
            "model_path": str(args.model_path.resolve()) if args.backend == "local" else None,
            "model_manifest_sha256": digest(model_manifest) if model_manifest.is_file() else None,
            "query_prefix": QUERY_PREFIX, "passage_prefix": PASSAGE_PREFIX,
            "maximum_text_characters": MAX_TEXT_CHARS,
            "maximum_query_model_tokens": MAX_QUERY_MODEL_TOKENS,
            "maximum_document_model_tokens": MAX_DOCUMENT_MODEL_TOKENS,
            "maximum_query_characters": 500,
            "maximum_query_search_tokens": MAX_QUERY_TOKENS,
            "batch_size": MAX_BATCH_SIZE, "cpu_threads": args.cpu_threads,
            "batch_size_scope": "maximum_passages_per_embedding_request",
            "maximum_model_forward_batch_size": MODEL_FORWARD_BATCH_SIZE,
            "model_device": "cpu", "model_dtype": "float32",
            "keyword_weight": settings.search_keyword_weight,
            "semantic_weight": settings.search_semantic_weight,
            "candidate_limit_per_channel": settings.search_max_candidates,
            "evaluation_top_k": 3,
            "keyword_acceptance_top_k": 1,
            "api_default_top_k": 10,
            "api_maximum_top_k": 50,
            "pooling": "none_token_vectors_retained",
            "normalization": "l2_per_token",
            "semantic_score_normalization": "sum_query_token_maxsim_divided_by_query_token_count",
            "token_index_storage": "c_owned_json_or_postgresql_jsonb",
            "legacy_dense_column": "unused_preserved_384_dimensions",
            "ai_request_timeout_seconds": settings.search_request_timeout_seconds,
            "local_in_process_timeout": "no_http_deadline" if args.backend == "local" else None,
            "parser_chunk_characters": CHUNK_SIZE_CHARS,
            "parser_chunk_overlap": CHUNK_OVERLAP_CHARS,
            "parser_minimum_chunk_characters": MIN_CHUNK_CHARS,
            "network_at_inference": "local_only_no_cloud_fallback",
            "page_navigation_enabled": args.page_navigation,
            "retrieval_profile": NAVIGATION_PROFILE if args.page_navigation else PLAIN_PROFILE,
            "page_count_source": "verified_pdf_version_metadata",
            "even_middle_policy": "both_central_physical_pages_ranked_by_existing_score",
        }
        (REPO / "work").mkdir(exist_ok=True)
        engine = make_engine(args.database_url)
        try:
            report["database"]["dialect"] = engine.dialect.name
            report["database"].update(prepare_schema(engine, args.database_url))
            with make_session_factory(engine)() as db:
                if engine.dialect.name == "postgresql":
                    report["database"]["version"] = db.scalar(text("SELECT version()"))
                    report["database"]["pgvector"] = db.scalar(text(
                        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                    ))
                else:
                    report["database"]["version"] = db.scalar(text("SELECT sqlite_version()"))
                report.update(evaluate_corpus(db, corpus_dir, gold, manifest, settings, backend))
                report["corpus_directory"] = str(corpus_dir.resolve())
                report["status"] = "evaluated"
                report["configuration"]["model_status"] = (
                    "disabled" if args.backend == "off" else
                    "partial" if report["pipeline"]["embedded_chunks_this_run"]
                    and report["pipeline"]["embedding_errors"] else
                    "available" if report["pipeline"]["embedded_chunks_this_run"] else
                    "unavailable"
                )
        finally:
            engine.dispose()
    except CorpusValidationError as exc:
        report.update(status="preflight_failed", diagnostics=exc.diagnostics)
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError) as exc:
        # Connection strings may contain passwords. Record the failure class,
        # while keeping driver exception bodies out of shareable evidence.
        report.update(status="execution_failed", diagnostics=[{
            "code": "database_unavailable" if isinstance(exc, SQLAlchemyError)
                    else "evaluation_input_unavailable",
            "exception_type": type(exc).__name__,
        }])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        report.get("summary", report.get("diagnostics")), ensure_ascii=False, indent=2
    ))
    print(f"Wrote evaluation: {args.output}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
