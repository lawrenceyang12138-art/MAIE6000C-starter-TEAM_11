from __future__ import annotations

import contextlib
from datetime import timedelta

from services.common.models import Job, JobStatus, utcnow
from services.worker.app import main as worker


def _job(db_session, **values):
    job = Job(
        job_type="scan_root",
        status=values.pop("status", JobStatus.PENDING.value),
        available_at=values.pop("available_at", utcnow()),
        **values,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_claim_skips_a_job_whose_retry_is_not_due(db_session, monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_lease_seconds", 60.0)
    _job(db_session, available_at=utcnow() + timedelta(minutes=5))

    assert worker.claim_next_pending_job(db_session) is None


def test_claim_records_a_lease_and_worker_identity(db_session, monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_lease_seconds", 60.0)
    job = _job(db_session)

    claimed = worker.claim_next_pending_job(db_session)

    assert claimed.id == job.id
    assert claimed.status == JobStatus.CLAIMED.value
    assert claimed.attempts == 1
    assert claimed.claimed_at is not None
    assert claimed.lease_expires_at is not None
    assert claimed.worker_id


def test_retry_wait_uses_backoff_and_preserves_attempts(
    db_session, monkeypatch
):
    monkeypatch.setattr(worker.settings, "worker_max_attempts", 3)
    monkeypatch.setattr(worker.settings, "worker_retry_base_seconds", 2.0)
    job = _job(db_session, status=JobStatus.CLAIMED.value, attempts=1)
    monkeypatch.setattr(
        worker,
        "get_session_factory",
        lambda: lambda: contextlib.nullcontext(db_session),
    )

    worker.mark_job_retry(job.id, "ai_timeout")

    db_session.refresh(job)
    assert job.status == JobStatus.RETRY_WAIT.value
    assert job.attempts == 1
    assert job.error == "ai_timeout"
    assert job.available_at is not None
    assert job.claimed_at is None
    assert job.lease_expires_at is None


def test_retry_exhaustion_becomes_a_terminal_failure(db_session, monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_max_attempts", 2)
    job = _job(db_session, status=JobStatus.CLAIMED.value, attempts=2)
    monkeypatch.setattr(
        worker,
        "get_session_factory",
        lambda: lambda: contextlib.nullcontext(db_session),
    )

    worker.mark_job_retry(job.id, "ai_timeout")

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED.value
    assert job.error.startswith("retry_exhausted:")
    assert job.claimed_at is None


def test_stale_claim_is_returned_to_retry_wait(db_session, monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_max_attempts", 3)
    job = _job(
        db_session,
        status=JobStatus.CLAIMED.value,
        attempts=1,
        claimed_at=utcnow() - timedelta(minutes=2),
        lease_expires_at=utcnow() - timedelta(seconds=1),
        available_at=utcnow() - timedelta(minutes=2),
    )

    worker._recover_stale_jobs(db_session)

    db_session.refresh(job)
    assert job.status == JobStatus.RETRY_WAIT.value
    assert job.error == "stale_claim_recovered"
    assert job.claimed_at is None
    assert job.lease_expires_at is None
