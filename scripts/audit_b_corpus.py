"""Audit B's clean-scan corpus and emit a D-consumable relation sample.

This script intentionally uses temporary copies. It never edits the committed
demo corpus or the frozen search answers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app.main import app
from services.common.config import get_settings
from services.common.db import Base, get_db, make_engine, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
    VersionStatus,
)
from services.parsing.handler import handle_extract_file
from services.scan.handler import handle_scan_root, resolve_source_path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


def _add_root(session, relative_path: str) -> AuthorizedRoot:
    root = AuthorizedRoot(
        mount_id="corpus",
        relative_path=relative_path,
        status=RootStatus.ACTIVE.value,
    )
    session.add(root)
    session.commit()
    return root


def _scan_and_extract(session, root: AuthorizedRoot) -> list[FileVersion]:
    handle_scan_root(session, root.id)
    versions = session.execute(
        select(FileVersion)
        .join(FileRecord, FileRecord.id == FileVersion.file_id)
        .where(FileRecord.root_id == root.id)
        .order_by(FileRecord.relative_path)
    ).scalars().all()
    for version in versions:
        handle_extract_file(
            session,
            version.id,
            resolve_source_path(session, version.id),
        )
    session.expire_all()
    return versions


def _corpus_record(session, version: FileVersion) -> dict:
    file_record = session.get(FileRecord, version.file_id)
    chunks = session.execute(
        select(SourceChunk)
        .where(SourceChunk.version_id == version.id)
        .order_by(SourceChunk.ordinal)
    ).scalars().all()
    page_fragments = [
        {
            "ordinal": chunk.ordinal,
            "page_number": chunk.page_number,
            "text": chunk.text,
        }
        for chunk in chunks
    ]
    return {
        "file_id": file_record.id,
        "version_id": version.id,
        "relative_path": file_record.relative_path,
        "content_sha256": version.content_sha256,
        "byte_size": version.byte_size,
        "status": version.status,
        "error_code": version.error_code,
        "parser_revision": version.parser_revision,
        "pages": sorted({chunk.page_number for chunk in chunks}),
        "chunks": page_fragments,
    }


def _relation_sample(session) -> dict:
    version = session.execute(
        select(FileVersion)
        .join(FileRecord, FileRecord.id == FileVersion.file_id)
        .where(FileRecord.relative_path == "entities.pdf")
    ).scalars().one()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get(f"/versions/{version.id}/relations")
            response.raise_for_status()
            relations = response.json()
            evidence_by_chunk = {}
            for relation in relations:
                chunk_id = relation["chunk_id"]
                if chunk_id is None or chunk_id in evidence_by_chunk:
                    continue
                evidence_response = client.get(f"/evidence/{chunk_id}")
                evidence_response.raise_for_status()
                evidence_by_chunk[chunk_id] = evidence_response.json()
    finally:
        app.dependency_overrides.clear()

    return {
        "source_pdf": "tests/fixtures/relations/entities.pdf",
        "version_id": version.id,
        "relation_response": relations,
        "evidence_by_chunk_id": evidence_by_chunk,
        "usage": {
            "list": f"GET /versions/{version.id}/relations",
            "evidence": "GET /evidence/{relation.chunk_id}",
            "review": "POST /relations/{relationship_id}/reviews",
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="b-corpus-audit-") as temp:
        temp_path = Path(temp)
        source_root = temp_path / "source"
        source_root.mkdir()
        get_settings().source_mounts = {"corpus": str(source_root)}

        corpus = source_root / "corpus"
        shutil.copytree(FIXTURES / "regression", corpus / "regression")
        abnormal = corpus / "abnormal"
        abnormal.mkdir()
        for name in ("corrupt.pdf", "encrypted.pdf", "no_text_layer.pdf"):
            shutil.copyfile(FIXTURES / "parsing" / name, abnormal / name)
        relations_root = source_root / "relations"
        relations_root.mkdir()
        shutil.copyfile(
            FIXTURES / "relations" / "entities.pdf",
            relations_root / "entities.pdf",
        )
        proposal_root = source_root / "d-proposal"
        proposal_root.mkdir()
        for directory in ("normal", "abnormal", "unsupported"):
            shutil.copytree(
                REPO / "fixtures" / directory,
                proposal_root / directory,
            )

        engine = make_engine(f"sqlite:///{temp_path / 'audit.db'}")
        Base.metadata.create_all(engine)
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            corpus_versions = _scan_and_extract(session, _add_root(session, "corpus"))
            relation_versions = _scan_and_extract(
                session, _add_root(session, "relations")
            )
            proposal_versions = _scan_and_extract(
                session, _add_root(session, "d-proposal")
            )
            records = [_corpus_record(session, version) for version in corpus_versions]
            proposal_records = [
                _corpus_record(session, version) for version in proposal_versions
            ]
            status_counts = {
                "basic_ready": sum(
                    record["status"] == VersionStatus.BASIC_READY.value
                    for record in records
                ),
                "unsupported": sum(
                    record["status"] == VersionStatus.UNSUPPORTED.value
                    for record in records
                ),
            }
            assert len(records) == 16
            assert status_counts == {"basic_ready": 12, "unsupported": 4}
            assert {
                record["error_code"]
                for record in records
                if record["status"] == VersionStatus.UNSUPPORTED.value
            } == {"corrupt", "encrypted", "no_text_layer", "unsupported_format"}
            assert len(relation_versions) == 1
            proposal_status_counts = {
                "basic_ready": sum(
                    record["status"] == VersionStatus.BASIC_READY.value
                    for record in proposal_records
                ),
                "unsupported": sum(
                    record["status"] == VersionStatus.UNSUPPORTED.value
                    for record in proposal_records
                ),
            }
            assert len(proposal_records) == 16
            assert proposal_status_counts == {"basic_ready": 12, "unsupported": 4}
            assert {
                record["error_code"]
                for record in proposal_records
                if record["status"] == VersionStatus.UNSUPPORTED.value
            } == {"corrupt", "unsupported_format"}
            gold_validation = subprocess.run(
                [sys.executable, "scripts/validate_d_gold.py"],
                cwd=REPO,
                check=True,
                capture_output=True,
                text=True,
            )
            d_gold_validation = json.loads(gold_validation.stdout)
            proposal_by_path = {
                record["relative_path"]: record for record in proposal_records
            }
            manifest = json.loads(
                (REPO / "fixtures" / "manifest.json").read_text(encoding="utf-8")
            )
            manifest_mismatches = []
            for expected in manifest["files"]:
                actual = proposal_by_path[expected["relative_path"]]
                issues = []
                if actual["status"] != expected["expected_status"]:
                    issues.append(
                        {
                            "field": "status",
                            "proposal_value": expected["expected_status"],
                            "actual_value": actual["status"],
                        }
                    )
                if actual["error_code"] != expected["expected_error_code"]:
                    issues.append(
                        {
                            "field": "error_code",
                            "proposal_value": expected["expected_error_code"],
                            "actual_value": actual["error_code"],
                        }
                    )
                if len(actual["pages"]) != expected["page_count"]:
                    issues.append(
                        {
                            "field": "page_count",
                            "proposal_value": expected["page_count"],
                            "actual_value": len(actual["pages"]),
                        }
                    )
                if issues:
                    manifest_mismatches.append(
                        {
                            "relative_path": expected["relative_path"],
                            "issues": issues,
                        }
                    )

            result = {
                "schema_version": "b-corpus-review-v1",
                "reviewed_on": "2026-10-30",
                "reviewed_by": "B",
                "database": "temporary clean SQLite",
                "workflow": (
                    "temporary source copies -> handle_scan_root -> "
                    "handle_extract_file -> FastAPI TestClient response"
                ),
                "originals_modified": False,
                "evaluation_outputs_used_to_change_answers": False,
                "corpus": {
                    "label": "mounted backend integration corpus",
                    "source": "tests/fixtures/regression plus parsing abnormal PDFs",
                    "files_seen": len(records),
                    "status_counts": status_counts,
                    "manual_result": "passed",
                    "records": records,
                },
                "d_proposal_corpus": {
                    "label": "D-generated fixtures proposal",
                    "source": "fixtures/normal, fixtures/abnormal, fixtures/unsupported",
                    "files_seen": len(proposal_records),
                    "status_counts": proposal_status_counts,
                    "reason_counts": {
                        reason: sum(
                            record["error_code"] == reason
                            for record in proposal_records
                            if record["status"] == VersionStatus.UNSUPPORTED.value
                        )
                        for reason in ("corrupt", "unsupported_format")
                    },
                    "manual_result": "reviewed; proposal metadata mismatch",
                    "manifest_version": manifest["manifest_version"],
                    "manifest_mismatches": manifest_mismatches,
                    "records": proposal_records,
                },
                "d_gold_review": {
                    "validator": "scripts/validate_d_gold.py",
                    "status": d_gold_validation["status"],
                    "queries": d_gold_validation["queries"],
                    "pdf_locations_verified": d_gold_validation[
                        "pdf_locations_verified"
                    ],
                    "corpus_files_hash_verified": d_gold_validation[
                        "corpus_files_hash_verified"
                    ],
                    "retrieval_evaluation": d_gold_validation[
                        "retrieval_evaluation"
                    ],
                    "freeze_human_review": d_gold_validation["human_B_review"],
                    "note": (
                        "Source locations and hashes pass. The D-managed freeze "
                        "metadata still says pending and must be revised together "
                        "with the parser status/code mismatches above."
                    ),
                },
                "relation_sample": _relation_sample(session),
                "handoff_to_D": {
                    "freeze_owner": "D",
                    "instruction": (
                        "Use the relation response and chunk IDs as a separate relation "
                        "sample when creating the next unified frozen corpus. Do not "
                        "rewrite expected search answers from evaluation results."
                    ),
                },
            }
        engine.dispose()

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
