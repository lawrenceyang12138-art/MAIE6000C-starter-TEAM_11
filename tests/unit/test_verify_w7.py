"""Acceptance must not report completion while embeddings or evidence are missing."""

import argparse
import json

import httpx
import pytest
from sqlalchemy import create_engine

from scripts.verify_w7 import (
    CheckFailed,
    Verification,
    guard_output,
    index_job_coverage,
    is_settled,
    safe_database_identity,
)


def _state(embed_status=None):
    jobs = [
        {"id": 1, "job_type": "scan_root", "status": "completed", "version_id": None},
        {"id": 2, "job_type": "extract_file", "status": "completed", "version_id": "v1"},
    ]
    if embed_status:
        jobs.append({"id": 3, "job_type": "embed_file", "status": embed_status,
                     "version_id": "v1"})
    return {"files": [{"id": "f1"}], "versions": [{"id": "v1", "status": "basic_ready"}],
            "jobs": jobs}


@pytest.mark.parametrize("embed_status", [None, "pending", "claimed"])
def test_parse_completion_does_not_establish_pipeline_completion(embed_status):
    assert not is_settled(_state(embed_status))


def test_completed_embed_allows_the_settling_window_to_begin():
    assert is_settled(_state("completed"))


def test_completed_model_recovery_indexing_preserves_valid_coverage():
    jobs = _state("completed")["jobs"]
    jobs.append({"id": 4, "job_type": "embed_file", "status": "completed",
                 "version_id": "v1"})
    assert index_job_coverage(jobs, {"v1"})


def test_indexing_coverage_rejects_missing_ready_or_unsupported_targets():
    jobs = _state("completed")["jobs"]
    assert not index_job_coverage(jobs, {"v1", "v2"})
    jobs.append({"id": 4, "job_type": "embed_file", "status": "completed",
                 "version_id": "unsupported"})
    assert not index_job_coverage(jobs, {"v1"})


def test_indexing_coverage_rejects_duplicate_live_work_even_after_completed_history():
    jobs = _state("completed")["jobs"]
    jobs.append({"id": 4, "job_type": "embed_file", "status": "claimed",
                 "version_id": "v1"})
    assert index_job_coverage(jobs, {"v1"})
    jobs.append({"id": 5, "job_type": "embed_file", "status": "pending",
                 "version_id": "v1"})
    assert not index_job_coverage(jobs, {"v1"})


def test_report_identity_excludes_username_and_escaped_password():
    identity = safe_database_identity(
        "postgresql+psycopg://private-user:secret%40word@localhost:15481/acceptance"
    )
    assert "private-user" not in identity
    assert "secret" not in identity
    assert "localhost:15481/acceptance" in identity


def test_report_cannot_overwrite_sources_or_frozen_answers(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    for path in (source_root / "result.json", tmp_path / "gold-queries.json"):
        with pytest.raises(ValueError, match="overwrite"):
            guard_output(path, source_root, "postgresql+psycopg://localhost/acceptance")
    database = tmp_path / "state.json"
    with pytest.raises(ValueError, match="database"):
        guard_output(database, source_root, f"sqlite:///{database.as_posix()}")


def test_search_hit_evidence_mismatch_is_a_recorded_failure(tmp_path):
    evidence = {"chunk_id": "c1", "file_id": "f1", "version_id": "v1",
                "page_number": 2, "ordinal": 1, "relative_path": "doc.pdf", "text": "source"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=evidence))
    engine = create_engine("sqlite://")
    args = argparse.Namespace(base_url="http://localhost", database_url="sqlite://",
                              source_root=tmp_path)
    with httpx.Client(base_url=args.base_url, transport=transport) as client:
        verifier = Verification(client, engine, args)
        with pytest.raises(CheckFailed):
            verifier.evidence_matches({"chunk_id": "c1", "file_id": "f1", "version_id": "v1",
                                       "page": 1, "ordinal": 1, "file_path": "doc.pdf",
                                       "text": "source"})
        assert verifier.report["checks"][-1]["passed"] is False
    engine.dispose()


def test_diagnostic_exception_does_not_leak_database_credentials(tmp_path):
    engine = create_engine("sqlite://")
    args = argparse.Namespace(base_url="http://localhost", source_root=tmp_path,
                              database_url="postgresql+psycopg://private:secret@localhost/test")
    with httpx.Client(base_url=args.base_url) as client:
        verifier = Verification(client, engine, args)

        def failing_action():
            raise RuntimeError(args.database_url)

        assert not verifier.phase("database step", failing_action)
        serialized = json.dumps(verifier.report)
        assert "secret" not in serialized
        assert "private" not in serialized
        assert verifier.report["checks"][-1]["evidence"] == {"exception_type": "RuntimeError"}
    engine.dispose()
