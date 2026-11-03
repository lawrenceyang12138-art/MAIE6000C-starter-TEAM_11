"""CMD-friendly local utilities for member C; no mutating Git operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url

from services.common.config import Settings, get_settings
from services.common.db import make_engine, make_session_factory
from services.common.models import AuthorizedRoot, FileRecord, FileVersion
from services.search.embeddings import HTTPEmbeddingBackend, LocalPplxEmbeddingBackend
from services.search.indexing import embed_version, index_document
from services.search.page_metadata import prepare_version_page_metadata
from services.search.token_store import prepare_search_schema
from services.search.text import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_NAME,
    MODEL_DIRECTORY,
    MODEL_REVISION,
    PINNED_MODEL_SHA256,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE_MOUNT_ID = "search-fixtures"


@contextmanager
def fixture_source_mounts(fixture_root: Path):
    """Use the production mount resolver for isolated synthetic source bytes."""
    fixture_root = fixture_root.resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    protected = [REPO / "fixtures", REPO / "submissions", REPO / "tests"]
    if any(
        fixture_root == path.resolve() or fixture_root.is_relative_to(path.resolve())
        for path in protected
    ):
        raise ValueError("fixture_root_overlaps_protected_sources")
    previous = os.environ.get("SOURCE_MOUNTS")
    os.environ["SOURCE_MOUNTS"] = json.dumps({FIXTURE_MOUNT_ID: str(fixture_root)})
    get_settings.cache_clear()
    try:
        yield fixture_root
    finally:
        if previous is None:
            os.environ.pop("SOURCE_MOUNTS", None)
        else:
            os.environ["SOURCE_MOUNTS"] = previous
        get_settings.cache_clear()


def _fixture_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
    ):
        raise ValueError("fixture document path must be a clean relative POSIX path")
    return value


def _materialize_fixture_document(fixture_root: Path, document: dict) -> tuple[dict, int]:
    relative_path = _fixture_relative_path(document["path"])
    chunks = document.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("fixture document must contain chunks")
    if not all(isinstance(chunk, dict) for chunk in chunks):
        raise ValueError("fixture document chunks must be objects")
    source_text = "\n\n".join(str(chunk.get("text", "")) for chunk in chunks)
    source_bytes = source_text.encode("utf-8")
    source_path = fixture_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)
    prepared = dict(document)
    prepared["sha256"] = hashlib.sha256(source_bytes).hexdigest()
    return prepared, len(source_bytes)


def backfill_page_metadata(database_url: str, root_id: str, version_id: str | None) -> dict:
    """Only explicit, scoped operator commands may publish derived PDF metadata."""
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as db:
            root = db.get(AuthorizedRoot, root_id)
            if root is None or root.status not in {"active", "paused"}:
                raise ValueError("page_metadata_root_not_readable")
            statement = (
                select(FileVersion)
                .join(FileRecord, FileRecord.id == FileVersion.file_id)
                .where(
                    FileRecord.root_id == root_id,
                    FileRecord.current_version_id == FileVersion.id,
                    FileRecord.presence_status == "present",
                    FileVersion.status.in_(["basic_ready", "enriched"]),
                ).order_by(FileRecord.relative_path, FileVersion.id)
            )
            if version_id:
                statement = statement.where(FileVersion.id == version_id)
            versions = list(db.scalars(statement))
            if version_id and not versions:
                raise ValueError("page_metadata_version_outside_scope")
            records = []
            for version in versions:
                result = prepare_version_page_metadata(db, version.id)
                records.append(asdict(result))
            db.commit()
            errors = sum(item["error"] is not None for item in records)
            return {
                "root_id": root_id, "selected_current_versions": len(versions),
                "ready_versions": len(versions) - errors, "error_versions": errors,
                "versions": records, "passed": errors == 0,
            }
    finally:
        engine.dispose()


def verified_model_manifest(destination: Path) -> dict:
    """Verify content against the pinned revision before trusting a local manifest."""
    if set(PINNED_MODEL_SHA256) != set(MODEL_FILES):
        raise ValueError("pinned model checksum configuration is incomplete")
    checksums = {}
    for filename in MODEL_FILES:
        target = (destination / filename).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise ValueError("model preparation path is outside the destination")
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != PINNED_MODEL_SHA256[filename]:
            raise ValueError(f"pinned model checksum mismatch: {filename}")
        checksums[filename] = actual
    return {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": checksums}


def prepare_model(destination: Path) -> None:
    """Explicit operator download; service startup has its own progress-aware preparer."""
    from huggingface_hub import snapshot_download

    destination.mkdir(parents=True, exist_ok=True)
    filenames = list(MODEL_FILES)
    for filename in filenames:
        target = (destination / filename).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise ValueError("model preparation path is outside the destination")
        target.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=str(destination),
        allow_patterns=filenames,
        max_workers=3,
    )
    manifest = verified_model_manifest(destination)
    (destination / "model-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared local model: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=[
            "download-model", "migrate", "prepare-token-index", "seed", "index", "evaluate",
            "page-metadata",
        ]
    )
    parser.add_argument("--database-url", default="sqlite:///work/search-demo.db")
    parser.add_argument(
        "--model-path", type=Path, default=REPO / MODEL_DIRECTORY
    )
    parser.add_argument("--fixture", type=Path, default=REPO / "fixtures/search/mock-chunks.json")
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=REPO / "work/search-fixtures",
        help="Isolated source tree for the synthetic chunk-fixture mount",
    )
    parser.add_argument("--gold", type=Path, default=REPO / "fixtures/search/gold-queries.json")
    parser.add_argument("--backend", choices=["local", "http", "off"], default="local")
    parser.add_argument("--ai-url", default="http://127.0.0.1:8100")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--version-id", help="Required by the index worker handler command")
    parser.add_argument("--manifest", type=Path, help="Frozen team corpus manifest for evaluation")
    parser.add_argument("--root-id", help="Real scanned root UUID for team gold evaluation")
    parser.add_argument("--page-navigation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--freeze", type=Path, help="Optional immutable gold/manifest freeze record"
    )
    parser.add_argument("--output", type=Path, default=REPO / "work/search-evaluation.json")
    args = parser.parse_args()
    if args.action == "page-metadata" and not args.root_id:
        parser.error("page-metadata requires --root-id; global backfills are refused")
    if args.action == "download-model":
        prepare_model(args.model_path)
        return
    (REPO / "work").mkdir(exist_ok=True)
    if args.action == "migrate":
        config = Config(str(REPO / "alembic.ini"))
        config.attributes["database_url"] = args.database_url
        command.upgrade(config, "head")
        engine = make_engine(args.database_url)
        try:
            prepare_search_schema(engine)
        finally:
            engine.dispose()
        return
    if args.action == "prepare-token-index":
        engine = make_engine(args.database_url)
        try:
            prepare_search_schema(engine)
        finally:
            engine.dispose()
        print("Prepared C-owned token index schema; canonical tables unchanged")
        return
    if args.action == "page-metadata":
        from scripts.evaluate_team_pdf import (
            git_state, public_command, validate_report_destination,
        )

        if "--output" not in sys.argv and not any(
            argument.startswith("--output=") for argument in sys.argv
        ):
            args.output = REPO / "work/page-metadata.json"
        try:
            validate_report_destination(
                args.output,
                protected_files=[args.gold, args.fixture,
                    REPO / "submissions/week07/gold-queries.json",
                    REPO / "submissions/week07/gold-queries.freeze.json"]
                + ([args.manifest] if args.manifest else [])
                + ([args.freeze] if args.freeze else []),
                source_directories=[REPO / "fixtures", REPO / "work/team-pdf-corpus"]
                + [Path(value) for value in Settings(_env_file=None).source_mounts.values()],
            )
            database = make_url(args.database_url)
            if (database.get_backend_name() == "sqlite"
                    and database.database not in (None, ":memory:")):
                if args.output.resolve() == Path(database.database).resolve():
                    raise ValueError("output_path_conflict: report would overwrite its database")
            report = backfill_page_metadata(args.database_url, args.root_id, args.version_id)
        except ValueError as exc:
            parser.error(str(exc))
        report.update(command=public_command([
            sys.executable, "-m", "scripts.search_tools", *sys.argv[1:]
        ]), git=git_state())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
        return
    gold = manifest = manifest_path = None
    input_record = {}
    if args.action == "evaluate":
        from scripts.evaluate_team_pdf import validate_report_destination

        gold = json.loads(args.gold.read_text(encoding="utf-8"))
        manifest_path = args.manifest
        if manifest_path is None and gold.get("corpus_manifest"):
            manifest_path = REPO / gold["corpus_manifest"]
        try:
            validate_report_destination(
                args.output,
                protected_files=[args.gold, args.fixture]
                + ([manifest_path] if manifest_path else [])
                + ([args.freeze] if args.freeze else []),
                source_directories=[REPO / "fixtures", REPO / "work/team-pdf-corpus"],
            )
        except ValueError as exc:
            parser.error(str(exc))
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path else None
        )
        input_record["gold_sha256"] = hashlib.sha256(args.gold.read_bytes()).hexdigest()
        if manifest_path:
            input_record["manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
        if args.freeze:
            freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
            input_record["freeze"] = freeze
            input_record["freeze_sha256"] = hashlib.sha256(args.freeze.read_bytes()).hexdigest()
            diagnostics = []
            for field, code in (
                ("gold_sha256", "frozen_gold_hash_mismatch"),
                ("manifest_sha256", "frozen_manifest_hash_mismatch"),
            ):
                if freeze.get(field) != input_record.get(field):
                    diagnostics.append({
                        "code": code,
                        "expected_sha256": freeze.get(field),
                        "actual_sha256": input_record.get(field),
                    })
            input_record["freeze_verified"] = not diagnostics
            if diagnostics:
                from scripts.evaluate_team_pdf import public_command

                report = {
                    **input_record,
                    "status": "preflight_failed",
                    "passed": False,
                    "candidate_gate_passed": False,
                    "evaluation_valid": False,
                    "queries": [],
                    "diagnostics": diagnostics,
                    "command": public_command([
                        sys.executable, "-m", "scripts.search_tools", *sys.argv[1:]
                    ]),
                }
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
                print(f"Wrote evaluation: {args.output}")
                raise SystemExit(1)
    backend = None
    if args.backend == "local":
        backend = LocalPplxEmbeddingBackend(str(args.model_path), args.cpu_threads)
    elif args.backend == "http":
        backend = HTTPEmbeddingBackend(args.ai_url, timeout=args.timeout)
    use_fixture_mount = args.action == "seed" or (
        args.action == "evaluate" and manifest is None and args.root_id is None
    )
    mount_context = (
        fixture_source_mounts(args.fixture_root)
        if use_fixture_mount
        else nullcontext()
    )
    engine = make_engine(args.database_url)
    try:
        with mount_context, make_session_factory(engine)() as db:
            if args.action == "seed":
                fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
                embedding_errors = []
                for document in fixture["documents"]:
                    prepared, source_size = _materialize_fixture_document(
                        args.fixture_root, document
                    )
                    version = index_document(db, byte_size=source_size, **prepared)
                    if backend is not None:
                        result = embed_version(db, version.id, backend)
                        print(json.dumps(asdict(result)))
                        if result.embedding_error:
                            embedding_errors.append(result.embedding_error)
                db.commit()
                print(f"Seeded {len(fixture['documents'])} synthetic documents")
                if embedding_errors:
                    print(
                        "Text retained, but embedding failed. "
                        "Fix the model/service and re-run seed."
                    )
                    raise SystemExit(1)
            elif args.action == "index":
                if not args.version_id or backend is None:
                    parser.error("index requires --version-id and an embedding backend")
                result = embed_version(db, args.version_id, backend)
                db.commit()
                print(json.dumps(asdict(result), indent=2))
                if result.embedding_error:
                    raise SystemExit(1)
            else:
                from services.search.evaluation import evaluate_queries

                settings = Settings(
                    embedding_enabled=backend is not None,
                    embedding_cpu_threads=args.cpu_threads,
                    search_request_timeout_seconds=args.timeout,
                    search_page_navigation_enabled=args.page_navigation,
                    _env_file=None,
                )
                report = evaluate_queries(
                    db, gold, settings, backend, manifest=manifest, root_id=args.root_id
                )
                report.update(input_record)
                if manifest is None:
                    report["fixture_sha256"] = hashlib.sha256(
                        args.fixture.read_bytes()
                    ).hexdigest()
                from scripts.evaluate_team_pdf import git_state, public_command

                report["git"] = git_state()
                sha = report["git"]["sha"]
                report["git_sha"] = sha if sha != "unavailable" else None

                report["command"] = public_command([
                    sys.executable, "-m", "scripts.search_tools", *sys.argv[1:]
                ])
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
                print(f"Wrote evaluation: {args.output}")
                if not report["passed"]:
                    raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
