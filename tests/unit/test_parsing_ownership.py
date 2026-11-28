"""Ownership tests for the parser: a stale attempt must not publish anything.

The worker's publish guard rejects a commit whose attempt is gone. These tests
exercise the parser directly, because the dangerous paths are its own exception
branches: a refused publish raises StaleClaim, and that must never be turned
into a `failed` version over the new owner's result.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from services.common.db import make_session_factory
from services.common.models import (
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    SourceChunk,
    VersionStatus,
)
from services.parsing import handler as parsing_handler
from services.parsing.pdf import (
    REASON_FILE_MISSING,
    REASON_SOURCE_CHANGED,
    SourceChanged,
    SourceMissing,
)
from services.worker.app import main as worker_main

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / "normal.pdf"


@pytest.fixture()
def worker_db(db_session, monkeypatch):
    """Point the worker's session factory at the test database."""
    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: factory)
    return db_session




def _claimed_job(worker_db, make_file_version, status=VersionStatus.DISCOVERED.value):
    version_id = make_file_version(source_path=FIXTURE, status=status)
    file_id = worker_db.get(FileVersion, version_id).file_id
    worker_db.get(FileRecord, file_id).current_version_id = version_id
    worker_db.commit()
    job = Job(
        version_id=version_id,
        job_type=RootJobType.EXTRACT_FILE.value,
        status=JobStatus.PENDING.value,
    )
    worker_db.add(job)
    worker_db.commit()
    claim = worker_main.claim_next_pending_job(worker_db)
    assert claim is not None and claim.job_id == job.id
    return version_id, job.id, claim


def _take_over(worker_db, job_id, version_id):
    """Simulate a second worker reclaiming the job and publishing its version."""
    factory = make_session_factory(worker_db.get_bind())
    with factory() as other:
        row = other.get(Job, job_id)
        row.attempts += 1
        row.lease_owner = "worker-b"
        other.commit()
        version = other.get(FileVersion, version_id)
        version.status = VersionStatus.ENRICHED.value
        version.error_code = None
        other.commit()


def test_a_stale_attempt_is_refused_before_the_reader_starts(
    worker_db, make_file_version, monkeypatch
):
    version_id, job_id, claim = _claimed_job(worker_db, make_file_version)
    _take_over(worker_db, job_id, version_id)

    def forbid(*args, **kwargs):
        pytest.fail("a stale attempt must not read the document at all")

    monkeypatch.setattr(parsing_handler, "extract_document", forbid)
    stale = worker_main.Claim(job_id, claim.attempts, claim.owner)

    with pytest.raises(worker_main.StaleClaim):
        parsing_handler.handle_extract_file(
            worker_db, version_id, FIXTURE, guard=worker_main._claim_guard(worker_db, stale)
        )

    worker_db.expire_all()
    version = worker_db.get(FileVersion, version_id)
    assert version.status == VersionStatus.ENRICHED.value
    assert version.error_code is None


@pytest.mark.parametrize("outcome", ["ready", "missing", "changed", "error"])
def test_a_late_result_never_overwrites_the_new_owner(
    worker_db, make_file_version, monkeypatch, outcome
):
    """A loses the claim while reading; every outcome must propagate StaleClaim."""
    version_id, job_id, claim = _claimed_job(worker_db, make_file_version)
    real_extract = parsing_handler.extract_document
    real_chunk = parsing_handler.chunk_document

    def extract_then_takeover(path):
        document = real_extract(path)
        _take_over(worker_db, job_id, version_id)
        return document

    def fail_after_takeover(*args, **kwargs):
        raise {
            "missing": SourceMissing(REASON_FILE_MISSING, "gone"),
            "changed": SourceChanged(REASON_SOURCE_CHANGED, "rewritten"),
            "error": RuntimeError("store failed"),
        }[outcome]

    if outcome == "ready":
        monkeypatch.setattr(parsing_handler, "extract_document", extract_then_takeover)
    else:
        monkeypatch.setattr(parsing_handler, "extract_document",
                            lambda path: (_take_over(worker_db, job_id, version_id),
                                          fail_after_takeover())[1])

    guard = worker_main._claim_guard(worker_db, claim)
    if outcome == "error":
        monkeypatch.setattr(parsing_handler, "chunk_document", fail_after_takeover)

    with pytest.raises(worker_main.StaleClaim):
        parsing_handler.handle_extract_file(worker_db, version_id, FIXTURE, guard=guard)

    worker_db.expire_all()
    version = worker_db.get(FileVersion, version_id)
    assert version.status == VersionStatus.ENRICHED.value, f"{outcome} wrote over the new owner"
    assert version.error_code is None
    assert not worker_db.scalars(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).all(), "a refused publish must not leave chunks behind"
    assert real_chunk is not None


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (None, None),
        (SourceMissing(REASON_FILE_MISSING, "gone"), REASON_FILE_MISSING),
        (SourceChanged(REASON_SOURCE_CHANGED, "rewritten"), REASON_SOURCE_CHANGED),
        (RuntimeError("store failed"), parsing_handler.REASON_PROCESSING_FAILED),
    ],
)
def test_the_current_owner_still_records_its_own_outcome(
    worker_db, make_file_version, monkeypatch, failure, expected_code
):
    """The guard must discard stale writes, not suppress genuine failures."""
    version_id, job_id, claim = _claimed_job(worker_db, make_file_version)

    if failure is not None:
        def raise_failure(path, _failure=failure):
            raise _failure
        monkeypatch.setattr(parsing_handler, "extract_document", raise_failure)

    if isinstance(failure, RuntimeError):
        # A non-document error is recorded and then re-raised for the worker.
        with pytest.raises(RuntimeError):
            parsing_handler.handle_extract_file(
                worker_db, version_id, FIXTURE,
                guard=worker_main._claim_guard(worker_db, claim),
            )
        status = VersionStatus.FAILED.value
    else:
        status = parsing_handler.handle_extract_file(
            worker_db, version_id, FIXTURE, guard=worker_main._claim_guard(worker_db, claim)
        )

    worker_db.expire_all()
    version = worker_db.get(FileVersion, version_id)
    if failure is None:
        assert status == VersionStatus.BASIC_READY.value
        assert version.status == VersionStatus.BASIC_READY.value
        assert version.error_code is None
    else:
        assert status == VersionStatus.FAILED.value
        assert version.status == VersionStatus.FAILED.value
        assert version.error_code == expected_code
