"""Tests for the worker's job dispatch.

The worker owns the dispatch loop for the read-files pipeline: it claims a
job, routes it by type, and records the outcome. These tests cover that
routing and the transaction rules around it - which job types are claimed,
what a handler's return value means for the job, and when a follow-up index
job is dispatched. The handlers themselves are covered by their own suites,
so they are replaced here and the dispatch logic is tested in isolation
against a real (SQLite) database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.db import make_session_factory
from services.common.models import (
    AuthorizedRoot,
    Case,
    CaseStatus,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    JobType,
    RootJobType,
    RootStatus,
    SourceChunk,
    VersionStatus,
)
from services.parsing.pdf import REASON_ENCRYPTED, REASON_FILE_MISSING
from services.search.embeddings import EmbeddingUnavailable, HTTPEmbeddingBackend
from services.search.indexing import IndexResult
from services.worker.app import main as worker_main


@pytest.fixture()
def worker_db(db_session: Session, monkeypatch):
    """Point the worker's session factory at the test database."""
    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: factory)
    return db_session


def _make_case(db: Session) -> str:
    case = Case(title="Printer down", description="The shared printer is down again.")
    db.add(case)
    db.commit()
    db.refresh(case)
    return case.id


def _make_job(db: Session, job_type: str, **targets) -> int:
    job = Job(job_type=job_type, status=JobStatus.PENDING.value, **targets)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.id


def _job(db: Session, job_id: int) -> Job:
    return db.get(Job, job_id)


def _index_jobs(db: Session, version_id: str) -> list[Job]:
    return list(
        db.execute(
            select(Job).where(
                Job.version_id == version_id,
                Job.job_type == RootJobType.EMBED_FILE.value,
            )
        )
        .scalars()
        .all()
    )


class _TriageResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"label": "incident", "summary": "Printer down: ...", "confidence": 0.83}


def test_a_triage_job_still_runs_the_starter_case_flow(worker_db, monkeypatch):
    case_id = _make_case(worker_db)
    job_id = _make_job(worker_db, JobType.TRIAGE_CASE.value, case_id=case_id)

    posted: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        posted.append({"url": url, "json": json})
        return _TriageResponse()

    monkeypatch.setattr(worker_main.httpx, "post", fake_post)

    worker_main.process_job(job_id)

    assert posted[0]["url"].endswith("/triage")
    assert posted[0]["json"]["case_id"] == case_id
    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value

    case = worker_db.get(Case, case_id)
    assert case.status == CaseStatus.TRIAGED.value
    assert case.ai_label == "incident"


def test_an_unknown_job_type_is_rejected(worker_db):
    job_id = _make_job(worker_db, "some_future_type")

    with pytest.raises(RuntimeError):
        worker_main.process_job(job_id)


def test_a_scan_job_runs_the_handler_and_completes(worker_db, monkeypatch):
    root = AuthorizedRoot(
        mount_id="corpus", relative_path=".", status=RootStatus.ACTIVE.value
    )
    worker_db.add(root)
    worker_db.commit()
    worker_db.refresh(root)
    job_id = _make_job(worker_db, RootJobType.SCAN_ROOT.value, root_id=root.id)

    seen: list[tuple] = []

    def fake_scan(db, root_id, job_id=None):
        seen.append((root_id, job_id))
        return {"outcome": "scanned", "files_seen": 3}

    monkeypatch.setattr(worker_main, "handle_scan_root", fake_scan)

    worker_main.process_job(job_id)

    # The job id is forwarded so the handler can skip concurrent scans.
    assert seen == [(root.id, job_id)]
    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value


def test_a_scan_error_propagates_for_the_loop_to_fail_the_job(worker_db, monkeypatch):
    root = AuthorizedRoot(
        mount_id="corpus", relative_path=".", status=RootStatus.ACTIVE.value
    )
    worker_db.add(root)
    worker_db.commit()
    worker_db.refresh(root)
    job_id = _make_job(worker_db, RootJobType.SCAN_ROOT.value, root_id=root.id)

    def boom(db, root_id, job_id=None):
        raise LookupError("unknown root")

    monkeypatch.setattr(worker_main, "handle_scan_root", boom)

    with pytest.raises(LookupError):
        worker_main.process_job(job_id)


def test_a_successful_extract_completes_the_job_and_dispatches_one_index_job(
    worker_db, make_file_version, monkeypatch
):
    version_id = make_file_version(sha256="b" * 64)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    seen: list[tuple] = []
    expected_path = Path("/source/corpus/reports/invoice.pdf")

    def fake_resolve(db, vid):
        seen.append(("resolve", vid))
        return expected_path

    def fake_extract(db, vid, source_path):
        seen.append(("extract", vid, str(source_path)))
        return VersionStatus.BASIC_READY.value

    monkeypatch.setattr(worker_main, "resolve_source_path", fake_resolve)
    monkeypatch.setattr(worker_main, "handle_extract_file", fake_extract)

    worker_main.process_job(job_id)

    assert seen == [
        ("resolve", version_id),
        ("extract", version_id, str(expected_path)),
    ]
    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value

    index_jobs = _index_jobs(worker_db, version_id)
    assert len(index_jobs) == 1
    assert index_jobs[0].status == JobStatus.PENDING.value
    assert index_jobs[0].version_id == version_id


def test_index_dispatch_is_idempotent_per_version(worker_db, make_file_version, monkeypatch):
    version_id = make_file_version(sha256="d" * 64)
    # A previous run already queued the index job; a re-run must not duplicate it.
    _make_job(worker_db, RootJobType.EMBED_FILE.value, version_id=version_id)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )
    monkeypatch.setattr(
        worker_main,
        "handle_extract_file",
        lambda db, vid, source_path: VersionStatus.BASIC_READY.value,
    )

    worker_main.process_job(job_id)

    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value
    assert len(_index_jobs(worker_db, version_id)) == 1


def test_an_unsupported_document_completes_the_job_without_indexing(
    worker_db, make_file_version, monkeypatch
):
    """``unsupported`` is a handled outcome: the document will never parse.

    The job is completed and carries ``error_code = NULL``: a completed job did
    not fail, and the document's reason stays on the version where ``GET /files``
    shows it.
    """
    version_id = make_file_version(sha256="e" * 64)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    def fake_extract(db, vid, source_path):
        version = db.get(FileVersion, vid)
        version.status = VersionStatus.UNSUPPORTED.value
        version.error_code = REASON_ENCRYPTED
        db.commit()
        return VersionStatus.UNSUPPORTED.value

    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )
    monkeypatch.setattr(worker_main, "handle_extract_file", fake_extract)

    worker_main.process_job(job_id)

    job = _job(worker_db, job_id)
    assert job.status == JobStatus.COMPLETED.value
    assert job.error_code is None
    assert _index_jobs(worker_db, version_id) == []
    # The reason is still recorded, on the version.
    assert worker_db.get(FileVersion, version_id).error_code == REASON_ENCRYPTED


def test_a_failed_version_fails_the_job_so_it_can_be_retried(
    worker_db, make_file_version, monkeypatch
):
    """A ``failed`` version must not leave the job saying ``completed``.

    That mismatch is what broke recovery: the version said "the file was not
    there", the job said "done", and ``POST /jobs/{id}/retry`` refused a
    completed job, so restoring the file changed nothing.
    """
    version_id = make_file_version(sha256="f" * 64)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    def fake_extract(db, vid, source_path):
        version = db.get(FileVersion, vid)
        version.status = VersionStatus.FAILED.value
        version.error_code = REASON_FILE_MISSING
        db.commit()
        return VersionStatus.FAILED.value

    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )
    monkeypatch.setattr(worker_main, "handle_extract_file", fake_extract)

    worker_main.process_job(job_id)

    job = _job(worker_db, job_id)
    assert job.status == JobStatus.FAILED.value
    # The reason travels with the job, so a client can tell a transient
    # "file_missing" from an internal failure.
    assert job.error_code == REASON_FILE_MISSING
    assert job.completed_at is not None
    assert _index_jobs(worker_db, version_id) == []


def test_an_unfinished_status_from_the_handler_is_a_bug(worker_db, make_file_version, monkeypatch):
    """A version left mid-pipeline must not be reported as finished work."""
    version_id = make_file_version(sha256="1" * 64)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )
    monkeypatch.setattr(
        worker_main,
        "handle_extract_file",
        lambda db, vid, source_path: VersionStatus.EXTRACTING.value,
    )

    with pytest.raises(RuntimeError):
        worker_main.process_job(job_id)


@pytest.mark.parametrize("embed_status", [status.value for status in JobStatus])
def test_a_retry_of_an_already_parsed_version_keeps_its_existing_index_job(
    worker_db, make_file_version, monkeypatch, embed_status
):
    """Retry is idempotent: published text is not replaced for nothing.

    Re-parsing would replace chunk rows, and chunk ids are what reviews and
    search indexes hang off. A version that already holds its text only needs
    its job closed - and no second index job, because the embeddings were
    built, or are the ``embed_file`` job's business.
    """
    version_id = make_file_version(sha256="2" * 64, status=VersionStatus.BASIC_READY.value)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)
    embed_id = _make_job(worker_db, RootJobType.EMBED_FILE.value, version_id=version_id)
    _job(worker_db, embed_id).status = embed_status
    worker_db.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )
    monkeypatch.setattr(
        worker_main,
        "handle_extract_file",
        lambda db, vid, source_path: calls.append("extract"),
    )

    worker_main.process_job(job_id)

    assert calls == []
    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value
    index_jobs = _index_jobs(worker_db, version_id)
    assert len(index_jobs) == 1
    assert index_jobs[0].id == embed_id
    assert index_jobs[0].status == embed_status


def test_retry_repairs_failed_first_index_dispatch_without_replacing_parsed_text(
    client, worker_db, make_file_version, monkeypatch
):
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / "normal.pdf"
    version_id = make_file_version(source_path=fixture)
    version = worker_db.get(FileVersion, version_id)
    worker_db.get(FileRecord, version.file_id).current_version_id = version_id
    worker_db.commit()
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)
    assert worker_main.claim_next_pending_job(worker_db).id == job_id
    real_enqueue = worker_main._enqueue_embed_job

    def fail_dispatch(*args, **kwargs):
        raise RuntimeError("index dispatch transaction failed")

    monkeypatch.setattr(worker_main, "_enqueue_embed_job", fail_dispatch)
    with pytest.raises(RuntimeError, match="index dispatch transaction failed"):
        worker_main.process_job(job_id)
    worker_main.mark_job_failed(job_id, "index dispatch transaction failed")
    worker_db.expire_all()
    assert worker_db.get(FileVersion, version_id).status == VersionStatus.BASIC_READY.value
    chunks = worker_db.scalars(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).all()
    chunk_ids = {chunk.id for chunk in chunks}
    assert chunk_ids
    assert _index_jobs(worker_db, version_id) == []

    monkeypatch.setattr(worker_main, "_enqueue_embed_job", real_enqueue)

    def no_reparse(*args, **kwargs):
        pytest.fail("a committed parse must retain its chunk and relation identities")

    monkeypatch.setattr(worker_main, "handle_extract_file", no_reparse)
    assert client.post(f"/jobs/{job_id}/retry").status_code == 202
    assert worker_main.claim_next_pending_job(worker_db).id == job_id
    worker_main.process_job(job_id)
    worker_db.expire_all()

    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value
    assert _job(worker_db, job_id).attempts == 2
    assert {chunk.id for chunk in worker_db.scalars(select(SourceChunk))} == chunk_ids
    assert len(_index_jobs(worker_db, version_id)) == 1

    def unavailable(*args, **kwargs):
        raise EmbeddingUnavailable("ai_unavailable")

    monkeypatch.setattr(HTTPEmbeddingBackend, "embed", unavailable)
    index_job = worker_main.claim_next_pending_job(worker_db)
    assert index_job.job_type == RootJobType.EMBED_FILE.value
    worker_main.process_job(index_job.id)
    worker_db.expire_all()
    assert {index.chunk_id for index in worker_db.scalars(select(ChunkSearchIndex))} == chunk_ids
    result = client.post("/search", json={"query": "ALPHA", "mode": "keyword"})
    assert result.status_code == 200
    assert result.json()["results"][0]["version_id"] == version_id


def test_a_retry_of_an_enriched_version_queues_no_index_job(
    worker_db, make_file_version, monkeypatch
):
    """``enriched`` already includes the vectors; there is nothing to re-queue."""
    version_id = make_file_version(sha256="4" * 64, status=VersionStatus.ENRICHED.value)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    monkeypatch.setattr(
        worker_main, "handle_extract_file", lambda db, vid, source_path: "unreachable"
    )

    worker_main.process_job(job_id)

    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value
    assert _index_jobs(worker_db, version_id) == []


def test_a_processing_error_propagates_for_the_loop_to_fail_the_job(
    worker_db, make_file_version, monkeypatch
):
    version_id = make_file_version(sha256="3" * 64)
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id)

    monkeypatch.setattr(
        worker_main, "resolve_source_path", lambda db, vid: Path("/corpus/x.pdf")
    )

    def boom(db, vid, source_path):
        raise RuntimeError("database went away")

    monkeypatch.setattr(worker_main, "handle_extract_file", boom)

    with pytest.raises(RuntimeError):
        worker_main.process_job(job_id)


def test_an_extract_job_without_a_version_is_rejected(worker_db):
    job_id = _make_job(worker_db, RootJobType.EXTRACT_FILE.value, version_id=None)

    with pytest.raises(RuntimeError):
        worker_main.process_job(job_id)


def test_an_index_job_builds_the_search_index_and_completes(
    worker_db, make_file_version, monkeypatch
):
    version_id = make_file_version()
    job_id = _make_job(worker_db, RootJobType.EMBED_FILE.value, version_id=version_id)

    seen: list[tuple] = []

    def fake_embed(db, vid, backend):
        seen.append((vid, backend))
        return IndexResult(version_id=vid, chunk_count=3, embedded_count=3)

    monkeypatch.setattr(worker_main, "embed_version", fake_embed)

    worker_main.process_job(job_id)

    assert seen[0][0] == version_id
    assert isinstance(seen[0][1], HTTPEmbeddingBackend)
    assert _job(worker_db, job_id).status == JobStatus.COMPLETED.value


def test_an_index_job_without_a_version_is_rejected(worker_db):
    job_id = _make_job(worker_db, RootJobType.EMBED_FILE.value, version_id=None)

    with pytest.raises(RuntimeError):
        worker_main.process_job(job_id)


def test_claiming_skips_job_types_the_worker_does_not_handle(worker_db, make_file_version):
    _make_job(worker_db, "some_future_type")
    version_id = make_file_version()
    extract_id = _make_job(
        worker_db, RootJobType.EXTRACT_FILE.value, version_id=version_id
    )

    claimed = worker_main.claim_next_pending_job(worker_db)

    assert claimed is not None
    assert claimed.id == extract_id
    assert claimed.status == JobStatus.CLAIMED.value


def test_mark_job_failed_records_the_error_and_fails_the_case(worker_db):
    case_id = _make_case(worker_db)
    job_id = _make_job(worker_db, JobType.TRIAGE_CASE.value, case_id=case_id)

    worker_main.mark_job_failed(job_id, "ai timed out")

    job = _job(worker_db, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.error == "ai timed out"
    assert job.completed_at is not None
    assert worker_db.get(Case, case_id).status == CaseStatus.FAILED.value


def test_mark_job_failed_works_for_jobs_without_a_case(worker_db):
    root = AuthorizedRoot(
        mount_id="corpus", relative_path=".", status=RootStatus.ACTIVE.value
    )
    worker_db.add(root)
    worker_db.commit()
    worker_db.refresh(root)
    job_id = _make_job(worker_db, RootJobType.SCAN_ROOT.value, root_id=root.id)

    worker_main.mark_job_failed(job_id, "mount directory not found")

    job = _job(worker_db, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.error == "mount directory not found"
