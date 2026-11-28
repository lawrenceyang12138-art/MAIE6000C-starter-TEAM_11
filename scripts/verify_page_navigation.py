"""Verify frozen navigation behavior using real PDFs and synthetic token vectors.

This is a deterministic behavior regression, not model-quality evidence. It
generates its own source corpus, uses production scan/parse/index handlers, and
queries only its isolated root. Missing/stale metadata and unknown source pages
are explicitly injected after normal ingestion to exercise failure handling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from scripts.evaluate_team_pdf import (
    dependency_versions,
    digest,
    git_state,
    prepare_schema,
    public_command,
    source_mounts,
    validate_report_destination,
)
from services.common.config import Settings
from services.common.db import make_engine, make_session_factory
from services.common.models import AuthorizedRoot, FileRecord, FileVersion, SourceChunk
from services.common.schemas import SearchRequest
from services.parsing.evidence import read_evidence
from services.parsing.handler import handle_extract_file
from services.scan.handler import handle_scan_root, resolve_source_path
from services.search.indexing import embed_version
from services.search.page_metadata import VersionPageMetadata, load_page_metadata
from services.search.page_navigation import parse_page_intent
from services.search.retrieval import search_chunks
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "fixtures/search/page-navigation-v1.json"
FREEZE = REPO / "fixtures/search/page-navigation-v1.freeze.json"
MARKER = ".c-page-navigation-corpus.json"


class NavigationRegressionError(ValueError):
    """A safe diagnostic code without filesystem or database exception bodies."""


class DeterministicNavigationBackend:
    """Favor earlier pages without learning any query, filename or frozen answer."""

    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS
    evidence_kind = "hand_constructed_token_vectors_not_PPLX_inference"

    def embed(self, texts: list[str], kind: str = "passage") -> list[list[list[float]]]:
        result = []
        for value in texts:
            if kind == "query":
                x = 1.0
            else:
                matched = re.search(r"PhysicalLeaf\s+(\d+)", value)
                page = int(matched.group(1)) if matched else 20
                x = max(0.2, 0.96 - 0.015 * page)
            token = [x, math.sqrt(max(0.0, 1.0 - x * x)), *([0.0] * (TOKEN_DIMENSIONS - 2))]
            result.append([token])
        return result


def _source_snapshot(corpus: Path, fixture: dict) -> list[dict]:
    rows = []
    expected_paths = {record["relative_path"] for record in fixture["documents"]}
    actual_paths = {
        path.relative_to(corpus).as_posix() for path in corpus.rglob("*")
        if path.is_file() and path.name != MARKER
    }
    if actual_paths != expected_paths or any(path.is_symlink() for path in corpus.rglob("*")):
        raise NavigationRegressionError("navigation_corpus_paths_mismatch")
    for record in fixture["documents"]:
        path = corpus / record["relative_path"]
        rows.append({"relative_path": record["relative_path"], "sha256": digest(path),
                     "byte_size": path.stat().st_size})
    return rows


def prepare_corpus(corpus: Path, fixture: dict, fixture_hash: str) -> list[dict]:
    """Create exact task-owned files once; subsequent runs only verify their bytes."""
    corpus = corpus.resolve()
    marker_path = corpus / MARKER
    if corpus.exists() and any(corpus.iterdir()):
        if not marker_path.is_file():
            raise NavigationRegressionError("navigation_corpus_not_owned")
        marker = json.loads(marker_path.read_text("utf-8"))
        observed = _source_snapshot(corpus, fixture)
        if marker.get("fixture_sha256") != fixture_hash or marker.get("files") != observed:
            raise NavigationRegressionError("navigation_corpus_identity_mismatch")
        return observed

    import fitz

    corpus.mkdir(parents=True, exist_ok=True)
    for record in fixture["documents"]:
        path = (corpus / record["relative_path"]).resolve()
        if not path.is_relative_to(corpus):
            raise NavigationRegressionError("navigation_fixture_path_out_of_scope")
        path.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open() as document:
            for page_number in range(1, record["page_count"] + 1):
                page = document.new_page(width=595, height=842)
                if page_number in record.get("blank_pages", []):
                    continue
                lines = [f"Navigation regression {record['id']} PhysicalLeaf {page_number}."]
                if page_number in record.get("long_pages", []):
                    lines.extend(
                        f"PhysicalLeaf {page_number} passage {row}. "
                        "Evidence remains on this physical leaf across multiple chunks."
                        for row in range(1, 31)
                    )
                else:
                    lines.append("Original source passage for deterministic navigation checks.")
                remaining = page.insert_textbox(
                    fitz.Rect(40, 40, 555, 802), "\n".join(lines), fontsize=8,
                )
                if remaining < 0:
                    raise NavigationRegressionError("navigation_pdf_text_did_not_fit")
            document.set_metadata({"title": f"Navigation regression {record['id']}",
                                   "producer": "team11-c-page-navigation-regression-v1"})
            document.save(path, deflate=True)
    observed = _source_snapshot(corpus, fixture)
    marker_path.write_text(json.dumps({"fixture_sha256": fixture_hash, "files": observed},
                                     indent=2) + "\n", "utf-8")
    return observed


def assert_database_scope(engine, mount_id: str) -> None:
    """Refuse unrelated authorization scopes before schema or corpus writes."""
    if not inspect(engine).has_table("authorized_roots"):
        return
    with make_session_factory(engine)() as db:
        roots = list(db.scalars(select(AuthorizedRoot)))
        if any(root.mount_id != mount_id or root.relative_path != "." for root in roots):
            raise NavigationRegressionError("navigation_database_contains_other_roots")
        if any(root.status != "active" for root in roots):
            raise NavigationRegressionError("navigation_root_not_active")


def evidence_rows(db, response, corpus: Path, *, root_id: str, file_id: str) -> list[dict]:
    result = []
    for rank, hit in enumerate(response.results, 1):
        evidence = read_evidence(db, hit.chunk_id)
        valid = (
            hit.root_id == root_id and hit.file_id == file_id
            and evidence.file_id == hit.file_id and evidence.version_id == hit.version_id
            and evidence.page_number == hit.page and evidence.ordinal == hit.ordinal
            and evidence.text[:2000] == hit.text and evidence.relative_path == hit.file_path
        )
        path = resolve_source_path(db, hit.version_id, for_write=False)
        valid = valid and path.is_relative_to(corpus) and digest(path) == evidence.content_sha256
        result.append({"rank": rank, **hit.model_dump(mode="json"), "evidence": asdict(evidence),
                       "evidence_matches_result_and_source": valid})
    return result


def _ranking_identity(response) -> list[tuple]:
    return [(hit.file_id, hit.version_id, hit.chunk_id, hit.page, hit.score,
             hit.keyword_score, hit.semantic_score) for hit in response.results]


def evaluate_cases(db, fixture: dict, settings: Settings, corpus: Path, root, files) -> dict:
    backend = DeterministicNavigationBackend()
    documents = {record["id"]: record for record in fixture["documents"]}
    rows = []
    for case in fixture["cases"]:
        record = documents[case["document"]]
        source = files[record["relative_path"]]
        version = db.get(FileVersion, source.current_version_id)
        page_count, metadata_status = load_page_metadata(db, version)
        parsed = parse_page_intent(case["query"])
        actual_intent = parsed.intent.kind if parsed.intent is not None else None
        intent_valid = actual_intent == case["intent"]
        if case.get("page") is not None and parsed.intent is not None:
            intent_valid = intent_valid and parsed.intent.page == case["page"]
        if case.get("skipped"):
            intent_valid = intent_valid and parsed.skipped_reason == case["skipped"]
        executions = []
        for mode in ("semantic", "hybrid"):
            request = SearchRequest(query=case["query"], mode=mode, root_id=root.id,
                                    file_id=source.id, top_k=3)
            baseline = search_chunks(
                db, request, settings.model_copy(update={"search_page_navigation_enabled": False}),
                backend,
            )
            diagnostics = {}
            enhanced = search_chunks(db, request, settings, backend,
                                     navigation_diagnostics=diagnostics)
            ranked = evidence_rows(db, enhanced, corpus, root_id=root.id, file_id=source.id)
            baseline_ranked = evidence_rows(
                db, baseline, corpus, root_id=root.id, file_id=source.id,
            )
            behavior = case.get("behavior", "located")
            actual_pages = [hit.page for hit in enhanced.results]
            if behavior == "empty":
                behavior_valid = not enhanced.results
            elif behavior == "ordinary":
                behavior_valid = bool(enhanced.results) and (
                    _ranking_identity(enhanced) == _ranking_identity(baseline)
                )
                if case.get("metadata_status"):
                    code = "page_metadata_" + case["metadata_status"]
                    behavior_valid = behavior_valid and metadata_status == code and all(
                        code in hit.reason for hit in enhanced.results
                    )
            else:
                behavior_valid = bool(enhanced.results) and all(
                    hit.page in case["target_pages"] for hit in enhanced.results
                )
            decisions = diagnostics.get("files", [])
            if parsed.intent is None:
                diagnostics_valid = (
                    diagnostics.get("status") == "not_applied" and not decisions
                    and diagnostics.get("not_applied_reason") == parsed.skipped_reason
                )
            else:
                decision = decisions[0] if len(decisions) == 1 else {}
                diagnostics_valid = (
                    decision.get("file_id") == source.id
                    and decision.get("version_id") == version.id
                    and decision.get("metadata_status") == metadata_status
                    and decision.get("page_count") == page_count
                    and decision.get("eligible_chunk_count", 0) > 0
                )
                if page_count is None:
                    diagnostics_valid = diagnostics_valid and (
                        diagnostics.get("status") == "not_applied"
                        and decision.get("applied") is False
                        and decision.get("reason") == metadata_status
                    )
                else:
                    valid_targets = [page for page in case.get("target_pages", [])
                                     if 1 <= page <= page_count]
                    diagnostics_valid = diagnostics_valid and (
                        diagnostics.get("status") == "applied"
                        and decision.get("applied") is True
                        and decision.get("target_pages") == valid_targets
                    )
                    if enhanced.results:
                        diagnostics_valid = diagnostics_valid and (
                            decision.get("target_chunk_count", 0) > 0
                            and decision.get("selected_chunk_id") == enhanced.results[0].chunk_id
                            and decision.get("selected_page") == enhanced.results[0].page
                        )
                    else:
                        diagnostics_valid = diagnostics_valid and (
                            decision.get("target_chunk_count") == 0
                            and decision.get("selected_chunk_id") is None
                            and decision.get("selected_page") is None
                        )
            evidence_valid = all(
                hit["evidence_matches_result_and_source"] for hit in ranked + baseline_ranked
            )
            non_degraded = not enhanced.degraded and enhanced.effective_mode == mode
            executions.append({
                "requested_mode": mode, "request": request.model_dump(mode="json"),
                "response": enhanced.model_dump(mode="json"), "ranked_results": ranked,
                "baseline_response": baseline.model_dump(mode="json"),
                "baseline_ranked_results": baseline_ranked, "navigation": diagnostics,
                "actual_pages": actual_pages, "intent_valid": intent_valid,
                "behavior_valid": behavior_valid, "evidence_valid": evidence_valid,
                "diagnostics_valid": diagnostics_valid,
                "passed": (intent_valid and behavior_valid and evidence_valid
                           and diagnostics_valid and non_degraded),
            })
        rows.append({**case, "physical_page_count": record["page_count"],
                     "stored_page_count": page_count, "metadata_status": metadata_status,
                     "parsed_intent": asdict(parsed.intent) if parsed.intent else None,
                     "parse_skipped_reason": parsed.skipped_reason,
                     "executions": executions, "passed": all(x["passed"] for x in executions)})
    counts = {
        group: {"passed": sum(row["passed"] for row in rows if row["group"] == group),
                "total": sum(row["group"] == group for row in rows)}
        for group in ("positive", "negative")
    }
    return {"cases": rows, "summary": {
        **counts, "unique_cases": len(rows), "enhanced_executions": len(rows) * 2,
        "baseline_executions": len(rows) * 2,
        "passed_executions": sum(ex["passed"] for row in rows for ex in row["executions"]),
        "evidence_failures": sum(not ex["evidence_valid"] for row in rows
                                 for ex in row["executions"]),
        "behavior_failures": sum(not ex["behavior_valid"] for row in rows
                                 for ex in row["executions"]),
        "diagnostic_failures": sum(not ex["diagnostics_valid"] for row in rows
                                   for ex in row["executions"]),
    }, "passed": all(row["passed"] for row in rows)}


def run_verification(database_url: str, corpus: Path, fixture: dict, fixture_hash: str) -> dict:
    corpus = corpus.resolve()
    mount_id = "c-navigation-" + hashlib.sha256(str(corpus).encode()).hexdigest()[:12]
    engine = make_engine(database_url)
    try:
        assert_database_scope(engine, mount_id)
        before = prepare_corpus(corpus, fixture, fixture_hash)
        schema = prepare_schema(engine, database_url)
        settings = Settings(_env_file=None, source_mounts={mount_id: str(corpus)},
                            search_page_navigation_enabled=True)
        with source_mounts(settings), make_session_factory(engine)() as db:
            root = db.scalar(select(AuthorizedRoot).where(
                AuthorizedRoot.mount_id == mount_id, AuthorizedRoot.relative_path == ".",
            ))
            if root is None:
                root = AuthorizedRoot(mount_id=mount_id, relative_path=".", status="active")
                db.add(root)
                db.commit()
            existing = list(db.scalars(select(FileRecord).where(FileRecord.root_id == root.id)))
            expected = {record["relative_path"] for record in fixture["documents"]}
            if any(source.relative_path not in expected for source in existing):
                raise NavigationRegressionError("navigation_database_contains_other_files")
            scan = handle_scan_root(db, root.id)
            files = {source.relative_path: source for source in db.scalars(
                select(FileRecord).where(FileRecord.root_id == root.id)
            )}
            processing, injections = [], []
            for record in fixture["documents"]:
                source = files[record["relative_path"]]
                version_id = source.current_version_id
                status = handle_extract_file(db, version_id, resolve_source_path(db, version_id))
                if status != "basic_ready":
                    raise NavigationRegressionError("navigation_generated_pdf_not_readable")
                indexed = embed_version(db, version_id, DeterministicNavigationBackend())
                if indexed.embedding_error:
                    raise NavigationRegressionError("navigation_synthetic_token_index_failed")
                db.commit()
                count, metadata_status = load_page_metadata(db, db.get(FileVersion, version_id))
                if metadata_status != "ready" or count != record["page_count"]:
                    raise NavigationRegressionError("navigation_actual_pdf_metadata_mismatch")
                processing.append({"file_id": source.id, "version_id": version_id,
                                   "relative_path": source.relative_path, "status": status,
                                   "actual_page_count": count, "index": asdict(indexed)})
                metadata = db.get(VersionPageMetadata, version_id)
                if record.get("metadata") == "missing":
                    db.delete(metadata)
                    injections.append({"version_id": version_id, "kind": "remove_page_metadata"})
                elif record.get("metadata") == "stale":
                    metadata.policy_revision = "obsolete_regression_policy"
                    injections.append({"version_id": version_id, "kind": "stale_metadata_policy"})
                if record.get("chunk_pages") == "unknown":
                    for chunk in db.scalars(select(SourceChunk).where(
                        SourceChunk.version_id == version_id,
                    )):
                        chunk.page_number = None
                    injections.append({"version_id": version_id, "kind": "unknown_source_pages"})
                db.commit()
            evaluated = evaluate_cases(db, fixture, settings, corpus, root, files)
            after = _source_snapshot(corpus, fixture)
            evaluated.update({
                "database_schema": schema, "root_id": root.id, "mount_id": mount_id,
                "scan": scan, "pipeline": processing, "fault_injections": injections,
                "source_mounts": settings.source_mounts, "source_files": after,
                "source_bytes_unchanged": before == after,
                "model_inference": False,
                "scoring_evidence": DeterministicNavigationBackend.evidence_kind,
                "claim": "navigation_behavior_regression_not_model_semantic_quality",
            })
            evaluated["passed"] = evaluated["passed"] and evaluated["source_bytes_unchanged"]
            return evaluated
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///work/page-navigation-v1.db")
    parser.add_argument("--work-dir", type=Path, default=REPO / "work/page-navigation-v1")
    parser.add_argument("--output", type=Path, default=REPO / "work/page-navigation-v1.json")
    args = parser.parse_args()
    corpus = args.work_dir.resolve()
    try:
        validate_report_destination(
            args.output, protected_files=[FIXTURE, FREEZE,
                REPO / "submissions/week07/gold-queries.json",
                REPO / "submissions/week07/gold-queries.freeze.json"],
            source_directories=[REPO / "fixtures", corpus],
        )
        if REPO.is_relative_to(corpus) or corpus.is_relative_to(REPO / "fixtures"):
            raise ValueError("navigation_work_dir_overlaps_repository_sources")
        database = make_url(args.database_url)
        if database.get_backend_name() == "sqlite" and database.database not in (None, ":memory:"):
            if args.output.resolve() == Path(database.database).resolve():
                raise ValueError("output_path_conflict: report would overwrite its database")
    except ValueError as exc:
        parser.error(str(exc))
    report = {
        "report_schema": "c-page-navigation-regression-run-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": public_command([sys.executable, "-m", "scripts.verify_page_navigation",
                                   *sys.argv[1:]]),
        "git": git_state(), "runtime": dependency_versions(),
        "database": database.render_as_string(hide_password=True),
        "corpus_directory": str(corpus), "passed": False,
        "runner_source_sha256": digest(Path(__file__)),
    }
    try:
        freeze = json.loads(FREEZE.read_text("utf-8"))
        fixture_hash = digest(FIXTURE)
        if fixture_hash != freeze["fixture_sha256"]:
            raise NavigationRegressionError("navigation_fixture_frozen_hash_mismatch")
        fixture = json.loads(FIXTURE.read_text("utf-8"))
        counts = fixture["expected_counts"]
        if (len(fixture["cases"]) != counts["total"]
                or len({case["id"] for case in fixture["cases"]}) != counts["total"]
                or sum(case["group"] == "positive" for case in fixture["cases"]) != 24
                or sum(case["group"] == "negative" for case in fixture["cases"]) != 12):
            raise NavigationRegressionError("navigation_fixture_counts_invalid")
        report["frozen_inputs"] = {"fixture": FIXTURE.relative_to(REPO).as_posix(),
                                   "fixture_sha256": fixture_hash, "freeze": freeze,
                                   "freeze_sha256": digest(FREEZE)}
        report.update(run_verification(args.database_url, corpus, fixture, fixture_hash))
        report["status"] = "complete"
    except (NavigationRegressionError, OSError, ValueError, SQLAlchemyError) as exc:
        report.update(status="execution_failed", failure={
            "code": str(exc) if isinstance(exc, NavigationRegressionError) else
                    "navigation_database_error" if isinstance(exc, SQLAlchemyError) else
                    "navigation_input_unavailable", "exception_type": type(exc).__name__,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"status": report["status"], "passed": report["passed"],
                      "summary": report.get("summary"), "failure": report.get("failure"),
                      "output": str(args.output)}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
