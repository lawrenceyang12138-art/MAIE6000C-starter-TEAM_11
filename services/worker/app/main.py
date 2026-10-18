from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_session_factory
from services.common.models import (
    Case,
    CaseStatus,
    Job,
    JobStatus,
    JobType,
    RootJobType,
    VersionStatus,
    utcnow,
)
from services.common.schemas import TriageResponse
from services.parsing.handler import handle_extract_file
from services.scan.handler import handle_scan_root, resolve_source_path
from services.search.embeddings import HTTPEmbeddingBackend
from services.search.indexing import embed_version

configure_logging()
logger = logging.getLogger("services.worker.main")
settings = get_settings()

# Job types this worker knows how to run. Jobs of other types stay pending
# instead of being claimed and failed - a type joins this set only once its
# handler exists.
#
# - triage_case: the starter Case flow (target: case_id).
# - scan_root / extract_file / embed_file: the read-files pipeline, targeting
#   root_id / version_id / version_id respectively (the shared contract's
#   job-type table). These must never enter the Case path, so their branches
#   run before any case lookup.
HANDLED_JOB_TYPES = {
    JobType.TRIAGE_CASE.value,
    RootJobType.SCAN_ROOT.value,
    RootJobType.EXTRACT_FILE.value,
    RootJobType.EMBED_FILE.value,
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


def _complete_job(db: Session, job: Job) -> None:
    """Close a job whose handler ran to a recorded outcome.

    Document-level problems (unsupported formats, changed or vanished
    sources) are recorded on the version by the handlers and count as
    completed outcomes here, not job failures - the shared contract calls
    them handled outcomes. Only errors that are not properties of the
    document reach run_worker's exception path and fail the job.
    """
    job.status = JobStatus.COMPLETED.value
    job.error = None
    job.completed_at = utcnow()
    db.commit()


def _enqueue_embed_job(db: Session, version_id: str) -> None:
    """Dispatch the search-index job for one successfully parsed version.

    Shared contract 3.4.3: index jobs are created only after source text is
    stored. Idempotent - a version keeps at most one live embed job, so a
    re-run never queues a duplicate. The caller commits.
    """
    existing = db.execute(
        select(Job)
        .where(
            Job.version_id == version_id,
            Job.job_type == RootJobType.EMBED_FILE.value,
            Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
        )
        .limit(1)
    ).scalars().first()
    if existing is not None:
        return
    db.add(
        Job(
            version_id=version_id,
            job_type=RootJobType.EMBED_FILE.value,
            status=JobStatus.PENDING.value,
        )
    )


def _embedding_backend() -> HTTPEmbeddingBackend:
    """The ai service owns the model. A missing or disabled model degrades
    search to keyword mode instead of failing the index job (contract 3.4.5).
    """
    return HTTPEmbeddingBackend(
        settings.ai_service_url, settings.search_request_timeout_seconds
    )


def _process_triage_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
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


def _process_scan_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        # Passing job.id lets the handler skip the run when another scan for
        # this root is already live, keeping repeated dispatch idempotent.
        summary = handle_scan_root(db, job.root_id, job.id)
        _complete_job(db, job)

    logger.info("scan_completed", extra={"job_id": job_id, "summary": summary})


def _process_extract_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        version_id = job.version_id
        if version_id is None:
            raise RuntimeError(f"extract_file job {job_id} has no version_id")

        source_path = resolve_source_path(db, version_id)
        # B's handler records the document outcome on the version and returns
        # the resulting status; only non-document errors raise.
        status = handle_extract_file(db, version_id, source_path)

        # Closing the extract job and dispatching the index job share one
        # transaction, so a crash cannot leave a parsed version unindexed.
        job.status = JobStatus.COMPLETED.value
        job.error = None
        job.completed_at = utcnow()
        if status == VersionStatus.BASIC_READY.value:
            _enqueue_embed_job(db, version_id)
        db.commit()

    logger.info(
        "extract_completed",
        extra={"job_id": job_id, "version_id": version_id, "version_status": status},
    )


def _process_embed_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        version_id = job.version_id
        if version_id is None:
            raise RuntimeError(f"embed_file job {job_id} has no version_id")

        # embed_version builds the keyword sidecars first and records an
        # embedding error instead of raising, so a missing model completes
        # the job with keyword-only search.
        result = embed_version(db, version_id, _embedding_backend())
        job.status = JobStatus.COMPLETED.value
        job.error = None
        job.completed_at = utcnow()
        db.commit()

    logger.info(
        "embed_completed",
        extra={
            "job_id": job_id,
            "version_id": version_id,
            "chunk_count": result.chunk_count,
            "embedded_count": result.embedded_count,
            "embedding_error": result.embedding_error,
        },
    )


def process_job(job_id: int) -> None:
    """Route one claimed job to its handler.

    The read-files branches never look up a Case: scan, extract and embed
    jobs target a root or a version, and their case_id is None.
    """
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job_type = job.job_type

    if job_type == JobType.TRIAGE_CASE.value:
        _process_triage_job(job_id)
    elif job_type == RootJobType.SCAN_ROOT.value:
        _process_scan_job(job_id)
    elif job_type == RootJobType.EXTRACT_FILE.value:
        _process_extract_job(job_id)
    elif job_type == RootJobType.EMBED_FILE.value:
        _process_embed_job(job_id)
    else:
        # claim_next_pending_job filters by HANDLED_JOB_TYPES; reaching here
        # means a job type was added to the table without a handler.
        raise RuntimeError(f"no handler for job type {job_type!r}")


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
