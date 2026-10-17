from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_session_factory
from services.common.models import (
    AuthorizedRoot,
    Case,
    CaseStatus,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    JobType,
    RootJobType,
    SourceChunk,
    VersionStatus,
    utcnow,
)
from services.common.schemas import TriageResponse
from services.parsing import (
    candidate_relations,
    handle_extract_file,
    persist_relations,
)
from services.scan import resolve_file_path, scan_root

configure_logging()
logger = logging.getLogger("services.worker.main")
settings = get_settings()

# Job types this worker knows how to run. Jobs of other types stay pending
# instead of being claimed and failed - for example a scan_root job created by
# POST /roots before the scan handler exists. Add a type here when its handler
# is implemented.
HANDLED_JOB_TYPES = {
    JobType.TRIAGE_CASE.value,
    RootJobType.SCAN_ROOT.value,
    RootJobType.EXTRACT_FILE.value,
}


def claim_next_pending_job(db: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.PENDING.value)
        .where(Job.job_type.in_(HANDLED_JOB_TYPES))
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    job = db.execute(stmt).scalars().first()
    if job is None:
        return None

    job.status = JobStatus.CLAIMED.value
    job.claimed_at = utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def mark_job_failed(job_id: int, error_message: str) -> None:
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        case = db.get(Case, job.case_id)
        job.status = JobStatus.FAILED.value
        job.error = error_message[:1000]
        job.completed_at = utcnow()

        if case is not None:
            case.status = CaseStatus.FAILED.value

        db.commit()


def _complete_job(db: Session, job_id: int, error: str | None = None) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    job.status = JobStatus.COMPLETED.value if error is None else JobStatus.FAILED.value
    job.error = error[:1000] if error is not None else None
    job.completed_at = utcnow()
    db.commit()


def _process_scan_root(db: Session, job: Job) -> None:
    if job.root_id is None:
        raise RuntimeError(f"scan_root job {job.id} has no root_id")
    root = db.get(AuthorizedRoot, job.root_id)
    if root is None:
        raise RuntimeError(f"Root not found for scan job {job.id}")

    summary = scan_root(db, root, settings.source_mounts)
    _complete_job(db, job.id)
    logger.info(
        "scan_completed",
        extra={
            "job_id": job.id,
            "root_id": root.id,
            "files_seen": summary.files_seen,
            "files_created": summary.files_created,
            "versions_created": summary.versions_created,
            "jobs_created": summary.jobs_created,
        },
    )


def _process_extract_file(db: Session, job: Job) -> None:
    if job.version_id is None:
        raise RuntimeError(f"extract_file job {job.id} has no version_id")
    version = db.get(FileVersion, job.version_id)
    if version is None:
        raise RuntimeError(f"File version not found for job {job.id}")
    file_record = db.get(FileRecord, version.file_id)
    if file_record is None:
        raise RuntimeError(f"File record not found for version {version.id}")
    root = db.get(AuthorizedRoot, file_record.root_id)
    if root is None:
        raise RuntimeError(f"Authorized root not found for file {file_record.id}")

    source_path = resolve_file_path(
        root.mount_id,
        root.relative_path,
        file_record.relative_path,
        settings.source_mounts,
    )
    outcome = handle_extract_file(db, version.id, source_path)

    if outcome == VersionStatus.BASIC_READY.value:
        chunks = list(
            db.execute(
                select(SourceChunk)
                .where(SourceChunk.version_id == version.id)
                .order_by(SourceChunk.ordinal)
            )
            .scalars()
            .all()
        )
        persist_relations(db, version.id, candidate_relations(chunks))
        _complete_job(db, job.id)
    elif outcome == VersionStatus.UNSUPPORTED.value:
        _complete_job(db, job.id)
    else:
        version = db.get(FileVersion, version.id)
        error = version.error_code if version is not None else None
        _complete_job(db, job.id, error or "extraction_failed")


def process_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        if job.job_type == RootJobType.SCAN_ROOT.value:
            _process_scan_root(db, job)
            return

        if job.job_type == RootJobType.EXTRACT_FILE.value:
            _process_extract_file(db, job)
            return

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found for job {job_id}")

        payload = {
            "case_id": case.id,
            "title": case.title,
            "description": case.description,
        }

    response = httpx.post(
        f"{settings.ai_service_url}/triage",
        json=payload,
        timeout=settings.worker_request_timeout_seconds,
    )
    response.raise_for_status()
    triage = TriageResponse.model_validate(response.json())

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found while completing job {job_id}")

        case.status = CaseStatus.TRIAGED.value
        case.ai_label = triage.label
        case.ai_summary = triage.summary
        case.ai_confidence = triage.confidence

        job.status = JobStatus.COMPLETED.value
        job.error = None
        job.completed_at = utcnow()
        db.commit()

    logger.info("job_completed", extra={"job_id": job_id, "label": triage.label})


def run_worker() -> None:
    session_factory = get_session_factory()
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "ai_service_url": settings.ai_service_url,
        },
    )

    while True:
        job = None
        try:
            with session_factory() as db:
                job = claim_next_pending_job(db)

            if job is None:
                time.sleep(settings.worker_poll_seconds)
                continue

            logger.info("job_claimed", extra={"job_id": job.id, "case_id": job.case_id})
            process_job(job.id)

        except KeyboardInterrupt:
            logger.info("worker_stopped")
            raise

        except Exception as exc:
            logger.exception("job_processing_failed")
            if job is not None:
                mark_job_failed(job.id, str(exc))
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run_worker()
