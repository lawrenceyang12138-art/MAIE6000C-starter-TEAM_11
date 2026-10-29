"""End-to-end recovery: authorize, scan, fail, restore, retry, parse.

This is the loop the A2 requirement is about, run through the real HTTP
handlers, the real scan handler, the real extraction handler and the real
worker dispatch, against a real (temporary) corpus and a real database. Only
the worker's session factory and the mount allowlist are pointed at the test
double; nothing in the pipeline is stubbed.

Fault injection is confined to a copy of a fixture PDF under ``tmp_path``. The
repository fixtures are never modified: the broken state is produced by removing
the copy, which is what "the source went away for a moment" looks like to the
scanner.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app import main as api_main
from services.common.db import make_session_factory
from services.common.models import (
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    SourceChunk,
    VersionStatus,
)
from services.parsing.pdf import REASON_FILE_MISSING
from services.scan import handler as scan_handler
from services.worker.app import main as worker_main

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / "normal.pdf"
DOCUMENT = "lecture.pdf"


class _Settings:
    def __init__(self, source_mounts: dict[str, str]) -> None:
        self.source_mounts = source_mounts


@pytest.fixture()
def corpus(tmp_path, monkeypatch, db_session: Session):
    """A writable copy of one real PDF, served as the allowlisted mount."""
    root = tmp_path / "corpus"
    root.mkdir()
    shutil.copyfile(FIXTURE_PDF, root / DOCUMENT)

    settings = _Settings({"corpus": str(root)})
    # The API validates and the worker resolves through the same allowlist.
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    monkeypatch.setattr(scan_handler, "get_settings", lambda: settings)

    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: factory)
    return root


def _authorize(client) -> tuple[str, int]:
    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "."}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    return body["root_id"], body["job_id"]


def _open_jobs(db: Session, **filters) -> list[Job]:
    return list(
        db.execute(
            select(Job).filter_by(status=JobStatus.PENDING.value, **filters)
        ).scalars()
    )


def _run_next_job(db: Session) -> Job:
    """Claim and run one job the way the worker loop does.

    The claim is part of the contract under test: it is what records the
    attempt, so calling the handler directly would hide whether attempts are
    preserved across a retry.
    """
    job = worker_main.claim_next_pending_job(db)
    assert job is not None, "expected a pending job to claim"
    worker_main.process_job(job.id)
    return job


def _extract_jobs(db: Session, version_id: str) -> list[Job]:
    return list(
        db.execute(
            select(Job).where(
                Job.version_id == version_id,
                Job.job_type == RootJobType.EXTRACT_FILE.value,
            )
        ).scalars()
    )


def _only_file(db: Session) -> FileRecord:
    return db.execute(select(FileRecord)).scalars().one()


def _version_of(db: Session, record: FileRecord) -> FileVersion:
    return db.get(FileVersion, record.current_version_id)


def _scan_and_collect(db: Session, client, root_id: str) -> int:
    """Queue another scan through the API and return its job id."""
    response = client.post(f"/roots/{root_id}/scans")
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_a_temporary_source_loss_recovers_through_an_explicit_retry(client, corpus, db_session):
    """The whole loop: scan, fail on a vanished file, restore, retry, parse.

    Before this change the failure was recorded on the version while the job
    said ``completed``, so the retry endpoint refused it and restoring the file
    changed nothing: the version stayed ``failed`` for good.
    """
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)

    record = _only_file(db_session)
    version = _version_of(db_session, record)
    assert version.status == VersionStatus.DISCOVERED.value
    extract_job = _extract_jobs(db_session, version.id)
    assert len(extract_job) == 1
    extract_job_id = extract_job[0].id
    sha_before = version.content_sha256

    # The source goes away between the scan and the extraction.
    (corpus / DOCUMENT).unlink()
    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version.id)
    failed_job = db_session.get(Job, extract_job_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_FILE_MISSING
    # The job must fail too, otherwise it can never be retried.
    assert failed_job.status == JobStatus.FAILED.value
    assert failed_job.error_code == REASON_FILE_MISSING
    assert failed_job.attempts == 1

    # The API says the same thing, with a stable code and no diagnostic text.
    body = client.get(f"/jobs/{extract_job_id}").json()
    assert body["status"] == "failed"
    assert body["error_code"] == REASON_FILE_MISSING
    assert body["attempts"] == 1

    # Same bytes come back. A rescan sees the same content, so it adds no
    # version and queues no second extraction.
    shutil.copyfile(FIXTURE_PDF, corpus / DOCUMENT)
    rescan_job_id = _scan_and_collect(db_session, client, root_id)
    worker_main.process_job(rescan_job_id)

    db_session.expire_all()
    record = _only_file(db_session)
    assert record.presence_status == FilePresence.PRESENT.value
    assert record.presence_reason is None
    assert record.current_version_id == version.id
    assert len(_extract_jobs(db_session, version.id)) == 1
    assert _version_of(db_session, record).content_sha256 == sha_before
    # Still failed: a scan is not an implicit retry.
    assert _version_of(db_session, record).status == VersionStatus.FAILED.value

    # The explicit retry is what reprocesses it.
    retry = client.post(f"/jobs/{extract_job_id}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json() == {
        "job_id": extract_job_id,
        "root_id": root_id,
        "status": "pending",
    }

    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version.id)
    job = db_session.get(Job, extract_job_id)
    assert version.status == VersionStatus.BASIC_READY.value
    assert version.error_code is None
    assert version.parser_revision is not None
    assert job.status == JobStatus.COMPLETED.value
    assert job.error_code is None
    # Attempts are provenance: the second run adds one, none are lost.
    assert job.attempts == 2

    chunks = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version.id)
    ).scalars().all()
    assert chunks, "the recovered version must carry its extracted text"
    # Re-processing did not duplicate passages: ordinals stay unique per version.
    ordinals = [chunk.ordinal for chunk in chunks]
    assert len(ordinals) == len(set(ordinals))

    # Source text is stored, so the search index job is queued - and only one.
    embed_jobs = _open_jobs(
        db_session,
        version_id=version.id,
        job_type=RootJobType.EMBED_FILE.value,
    )
    assert len(embed_jobs) == 1


def test_a_retry_while_the_file_is_still_gone_fails_again_and_stays_retryable(
    client, corpus, db_session
):
    """Repeating a retry is idempotent: one job row, more attempts, no copies."""
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    extract_job_id = _extract_jobs(db_session, version.id)[0].id

    (corpus / DOCUMENT).unlink()
    _run_next_job(db_session)
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 202

    # The file is still gone: the retry fails the same way, and stays retryable.
    _run_next_job(db_session)

    db_session.expire_all()
    job = db_session.get(Job, extract_job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.error_code == REASON_FILE_MISSING
    assert job.attempts == 2
    assert len(_extract_jobs(db_session, version.id)) == 1

    # A third explicit retry is still accepted, so the loop never dead-ends.
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 202


def test_repeated_scans_after_success_create_nothing_new(client, corpus, db_session):
    """Idempotency after the happy path: no files, versions or live jobs added.

    Each ``POST /roots/{id}/scans`` legitimately adds one scan job - that is the
    endpoint's contract - but nothing it dispatches may duplicate: no new file
    rows, no new versions, no second extraction for the same version.
    """
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    worker_main.process_job(_extract_jobs(db_session, version.id)[0].id)

    db_session.expire_all()
    files_before = db_session.query(FileRecord).count()
    versions_before = db_session.query(FileVersion).count()
    chunks_before = db_session.query(SourceChunk).count()

    for _ in range(2):
        worker_main.process_job(_scan_and_collect(db_session, client, root_id))

    assert db_session.query(FileRecord).count() == files_before
    assert db_session.query(FileVersion).count() == versions_before
    assert db_session.query(SourceChunk).count() == chunks_before
    # One extraction was ever queued for this version, and it is finished.
    assert len(_extract_jobs(db_session, version.id)) == 1
    # The only live work is the single search-index job queued once.
    open_jobs = _open_jobs(db_session)
    assert [job.job_type for job in open_jobs] == [RootJobType.EMBED_FILE.value]


def test_a_file_removed_after_a_scan_is_listed_as_missing_with_a_reason(
    client, corpus, db_session
):
    """A1 over HTTP: the row explains itself instead of silently staying present."""
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    worker_main.process_job(_extract_jobs(db_session, version.id)[0].id)

    (corpus / DOCUMENT).unlink()
    worker_main.process_job(_scan_and_collect(db_session, client, root_id))

    # The worker writes through its own session; drop the cached rows so the
    # API read reflects what it committed.
    db_session.expire_all()
    files = client.get("/files", params={"root_id": root_id}).json()
    assert len(files) == 1
    item = files[0]
    assert item["presence_status"] == "missing"
    assert item["presence_reason"] == REASON_FILE_MISSING
    # The indexed text is still described by its version; it is just not current.
    assert item["status"] == VersionStatus.BASIC_READY.value
    assert item["version_id"] == version.id


def test_an_unreadable_file_is_listed_as_unavailable_with_its_reason(
    client, corpus, db_session, monkeypatch
):
    """A1 over HTTP: "unreadable" is not "missing", and both are legible."""
    from services.parsing.pdf import REASON_UNREADABLE, SourceMissing

    root_id, scan_job_id = _authorize(client)
    real_identity = scan_handler.file_identity

    def flaky_identity(path):
        raise SourceMissing(REASON_UNREADABLE, "permission denied")

    monkeypatch.setattr(scan_handler, "file_identity", flaky_identity)
    worker_main.process_job(scan_job_id)
    monkeypatch.setattr(scan_handler, "file_identity", real_identity)

    files = client.get("/files", params={"root_id": root_id}).json()
    assert len(files) == 1
    assert files[0]["presence_status"] == "unavailable"
    assert files[0]["presence_reason"] == REASON_UNREADABLE
    # Nothing was read, so the file has no version and queued no job.
    assert files[0]["version_id"] is None
    assert db_session.query(FileVersion).count() == 0
    assert db_session.query(Job).count() == 1  # only the scan job itself
