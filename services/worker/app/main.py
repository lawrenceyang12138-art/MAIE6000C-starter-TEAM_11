from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.claim import StaleClaim
from services.common.db import get_session_factory
from services.common.models import (
    Case,
    CaseStatus,
    FileVersion,
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
from services.search.model_startup import SetupStatus
from services.search.startup_recovery import queue_startup_embeddings

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


LEASE_SECONDS = 60
LEASE_OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@dataclass
class Claim:
    """The identity of one attempt, carried to every write it authorizes.

    ``attempts`` increments on every claim, including a reclaim after expiry, so
    two attempts never share it. A worker that lost its lease compares this value
    and stops instead of publishing a stale result.
    """

    job_id: int
    attempts: int
    owner: str = LEASE_OWNER
    lost: bool = False


def _current_claim(db: Session, job_id: int) -> Claim | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    return Claim(job.id, job.attempts, job.lease_owner or LEASE_OWNER)


def _guard(claim: Claim, *, require_claimed: bool = False):
    conditions = [Job.id == claim.job_id, Job.attempts == claim.attempts]
    if require_claimed:
        conditions.append(Job.status == JobStatus.CLAIMED.value)
    return and_(*conditions)


def _finish(
    db: Session,
    claim: Claim,
    *,
    status: str,
    error: str | None = None,
    error_code: str | None = None,
    clear_lease: bool = True,
) -> bool:
    """Write a terminal job state only while this attempt still owns the row.

    The conditional update is the ownership check: an expired claim that another
    worker reclaimed has a different ``attempts``, so nothing is written and the
    caller learns it lost the job.
    """
    values = {
        "status": status,
        "error": error,
        "error_code": error_code,
        "completed_at": utcnow(),
    }
    if clear_lease:
        values["lease_owner"] = None
        values["lease_expires_at"] = None
    moved = db.execute(
        update(Job)
        .where(_guard(claim))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return moved.rowcount == 1


def _claimable(now):
    """Pending work, plus claimed work whose worker stopped renewing."""
    return or_(
        Job.status == JobStatus.PENDING.value,
        and_(
            Job.status == JobStatus.CLAIMED.value,
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at < now,
        ),
    )


def claim_next_pending_job(db: Session) -> Claim | None:
    """Claim one job and take its lease (ADR 0002).

    Selection and transition share one predicate, so a racing claimer cannot
    double-claim; PostgreSQL additionally skips rows another transaction holds.
    An expired lease makes the row claimable again, which is the whole point:
    a worker that dies mid-job stops stranding the work.
    """
    now = utcnow()
    stmt = (
        select(Job.id)
        .where(Job.job_type.in_(HANDLED_JOB_TYPES), _claimable(now))
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job_id = db.execute(stmt).scalar_one_or_none()
    if job_id is None:
        return None
    # RETURNING, not a re-read: another worker can reclaim this row the moment
    # the transaction commits, and a re-read would then hand this worker the new
    # owner's attempt number. The identity must come from our own update.
    moved = db.execute(
        update(Job)
        .where(Job.id == job_id, _claimable(now))
        .values(
            status=JobStatus.CLAIMED.value,
            claimed_at=now,
            attempts=Job.attempts + 1,
            lease_owner=LEASE_OWNER,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
        )
        .returning(Job.id, Job.attempts, Job.lease_owner)
        .execution_options(synchronize_session=False)
    )
    row = moved.first()
    if row is None:
        db.rollback()
        return None
    db.commit()
    return Claim(row.id, row.attempts, row.lease_owner)


def _renew_lease(claim: Claim) -> bool:
    """Return False when the row no longer belongs to this attempt."""
    session_factory = get_session_factory()
    with session_factory() as db:
        renewed = db.execute(
            update(Job)
            .where(_guard(claim, require_claimed=True))
            .values(lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS))
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return renewed.rowcount == 1


def _release_lease(job_id: int) -> None:
    session_factory = get_session_factory()
    with session_factory() as db:
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.lease_owner == LEASE_OWNER)
            .values(lease_owner=None, lease_expires_at=None)
            .execution_options(synchronize_session=False)
        )
        db.commit()


def _claim_guard(db: Session, claim: Claim):
    """Check-and-lock the job row inside the transaction that publishes data.

    Handlers do slow file I/O outside any lock; this runs immediately before
    their commit, takes the row lock for the duration of that transaction and
    refuses the publish when another attempt has taken over.
    """

    def check() -> bool:
        row = db.execute(
            select(Job.attempts).where(Job.id == claim.job_id).with_for_update()
        ).first()
        return row is not None and row.attempts == claim.attempts

    return check


@contextmanager
def _keep_lease(claim: Claim):
    """Renew while the job runs; a long embed must not lose its claim.

    A renewal that updates no row is a lost claim, not a transient error: mark
    it so the caller discards its result instead of publishing it.
    """
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(LEASE_SECONDS / 3):
            try:
                if not _renew_lease(claim):
                    claim.lost = True
                    logger.warning("lease_lost", extra={"job_id": claim.job_id})
                    return
            except Exception:  # noqa: BLE001 - the next tick retries
                logger.warning("lease_renewal_failed", extra={"job_id": claim.job_id})

    thread = threading.Thread(target=renew, name=f"lease-{claim.job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def mark_job_failed(
    job_id: int,
    error_message: str,
    error_code: str = "job_failed",
    *,
    claim: Claim | None = None,
) -> None:
    """Fail a job, but only the attempt that still owns it.

    Without ``claim`` the write is unconditional, which is what direct callers
    and tests expect. The worker always passes its claim: a suspended worker that
    wakes up after another attempt reclaimed the job must not fail that attempt
    or clear its lease.
    """
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        if claim is not None:
            moved = db.execute(
                update(Job)
                .where(_guard(claim, require_claimed=True))
                .values(
                    status=JobStatus.FAILED.value,
                    error=error_message[:1000],
                    error_code=error_code,
                    completed_at=utcnow(),
                    lease_owner=None,
                    lease_expires_at=None,
                )
                .execution_options(synchronize_session=False)
            )
            if moved.rowcount != 1:
                db.rollback()
                logger.warning("stale_failure_discarded", extra={"job_id": job_id})
                return
            # The job row is already failed by the guarded update; only the case
            # summary still needs the same transaction.
            case = db.get(Case, job.case_id) if job.case_id else None
            if case is not None:
                case.status = CaseStatus.FAILED.value
            db.commit()
            return

        # A scan or index job has no case; only triage jobs carry one.
        case = db.get(Case, job.case_id) if job.case_id else None
        job.status = JobStatus.FAILED.value
        job.error = error_message[:1000]
        job.error_code = error_code
        job.completed_at = utcnow()
        # A failed job holds no lease, whoever marked it failed.
        job.lease_owner = None
        job.lease_expires_at = None

        if case is not None:
            case.status = CaseStatus.FAILED.value

        db.commit()


def _complete_job(db: Session, job: Job) -> None:
    """Close a job whose handler ran to a recorded outcome.

    Document-level problems (unsupported formats) are recorded on the version
    by the handlers and count as completed outcomes here, not job failures -
    the shared contract calls them handled outcomes. Only errors that are not
    properties of the document reach run_worker's exception path and fail the
    job.
    """
    job.status = JobStatus.COMPLETED.value
    job.error = None
    job.error_code = None
    job.completed_at = utcnow()
    db.commit()


def _enqueue_embed_job(
    db: Session, version_id: str, *, first_dispatch_only: bool = False
) -> None:
    """Dispatch the search-index job for one successfully parsed version.

    Shared contract 3.4.3: index jobs are created only after source text is
    stored. Idempotent - a version keeps at most one live embed job, so a
    re-run never queues a duplicate. ``first_dispatch_only`` repairs a parse
    whose first dispatch failed, without retrying an existing finished job.
    The caller commits.
    """
    # Share this per-version lock with the model-ready recovery sweep.
    db.execute(select(FileVersion.id).where(FileVersion.id == version_id).with_for_update())
    existing_query = (
        select(Job)
        .where(
            Job.version_id == version_id,
            Job.job_type == RootJobType.EMBED_FILE.value,
        )
    )
    if not first_dispatch_only:
        existing_query = existing_query.where(
            Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value])
        )
    existing = db.execute(existing_query.limit(1)).scalars().first()
    if existing is not None:
        return
    if first_dispatch_only:
        # This retry can close an existing parse without reading it again,
        # but creating new work still requires an active, contained root.
        resolve_source_path(db, version_id)
    db.add(
        Job(
            version_id=version_id,
            job_type=RootJobType.EMBED_FILE.value,
            status=JobStatus.PENDING.value,
        )
    )


def _embedding_backend() -> HTTPEmbeddingBackend | None:
    """The ai service owns the model. A missing or disabled model degrades
    search to keyword mode instead of failing the index job (contract 3.4.5).
    """
    if not settings.embedding_enabled:
        return None
    return HTTPEmbeddingBackend(
        settings.ai_service_url, settings.search_request_timeout_seconds
    )


def _process_triage_job(claim: Claim) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, claim.job_id)
        if job is None:
            return
        if job.attempts != claim.attempts:
            raise StaleClaim(f"triage job {claim.job_id} moved to another attempt")

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found for job {claim.job_id}")

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

    # The case data and the job state are one decision: both are written only
    # while this attempt still owns the row. FOR UPDATE makes that check hold
    # against a reclaim that commits between the read and the write.
    with session_factory() as db:
        job = db.execute(
            select(Job).where(Job.id == claim.job_id).with_for_update()
        ).scalars().first()
        if job is None:
            return
        if job.attempts != claim.attempts:
            db.rollback()
            raise StaleClaim(f"triage job {claim.job_id} moved to another attempt")

        case = db.get(Case, job.case_id)
        if case is None:
            raise RuntimeError(f"Case not found while completing job {claim.job_id}")

        case.status = CaseStatus.TRIAGED.value
        case.ai_label = triage.label
        case.ai_summary = triage.summary
        case.ai_confidence = triage.confidence

        job.status = JobStatus.COMPLETED.value
        job.error = None
        job.completed_at = utcnow()
        job.lease_owner = None
        job.lease_expires_at = None
        db.commit()

    logger.info("job_completed", extra={"job_id": claim.job_id, "label": triage.label})


def _process_scan_job(claim: Claim) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, claim.job_id)
        if job is None:
            return

        # Passing job.id lets the handler skip the run when another scan for
        # this root is already live, keeping repeated dispatch idempotent.
        summary = handle_scan_root(db, job.root_id, job.id, guard=_claim_guard(db, claim))
        if not _finish(db, claim, status=JobStatus.COMPLETED.value):
            db.rollback()
            raise StaleClaim(f"scan job {claim.job_id} moved to another attempt")
        db.commit()

    logger.info("scan_completed", extra={"job_id": claim.job_id, "summary": summary})


def _extract_outcome(db: Session, claim: Claim, job: Job, version_id: str, status: str) -> None:
    """Record what a version outcome means for the job that produced it.

    The mapping is the one the shared contract implies, and it has to be
    explicit here because getting it wrong breaks recovery both ways:

    - ``basic_ready``: the text is stored, so the job is done and the index
      job is queued in the same transaction.
    - ``unsupported``: the document cannot be processed and never will be
      (encrypted, damaged, no text layer). A handled outcome; the job is done.
    - ``failed``: the version could not be processed *this time* - the file was
      gone, changed while being read, or the store errored. The version is
      recorded as failed, so the job must fail too. If the job said
      ``completed`` while the version said ``failed``, ``POST /jobs/{id}/retry``
      would refuse it as "not retryable" and the file could never recover.
      ``error_code`` carries the version's reason so a client can tell a
      transient failure from an internal one.

    Anything else is a handler bug: a version left mid-pipeline must not be
    reported as finished work.
    """
    if status == VersionStatus.BASIC_READY.value:
        # Queue the index job and close the attempt together: a lost claim must
        # roll both back, otherwise a stale worker leaves work nobody owns.
        _enqueue_embed_job(db, version_id)
        if not _finish(db, claim, status=JobStatus.COMPLETED.value):
            db.rollback()
            raise StaleClaim(f"extract job {claim.job_id} moved to another attempt")
        return

    if status in {VersionStatus.ENRICHED.value, VersionStatus.UNSUPPORTED.value}:
        # ENRICHED: text and vectors are both in place; nothing left to queue.
        # UNSUPPORTED: a handled document outcome, so the job succeeds and
        # ``error_code`` stays NULL - it means "the last attempt failed".
        if not _finish(db, claim, status=JobStatus.COMPLETED.value):
            db.rollback()
            raise StaleClaim(f"extract job {claim.job_id} moved to another attempt")
        return

    if status == VersionStatus.FAILED.value:
        version = db.get(FileVersion, version_id)
        reason = (version.error_code if version is not None else None) or "processing_failed"
        if not _finish(
            db, claim,
            status=JobStatus.FAILED.value,
            error=f"version {version_id} failed: {reason}"[:1000],
            error_code=reason,
        ):
            db.rollback()
            raise StaleClaim(f"extract job {claim.job_id} moved to another attempt")
        return

    raise RuntimeError(
        f"extract handler for {version_id} returned an unfinished status {status!r}"
    )


def _process_extract_job(claim: Claim) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, claim.job_id)
        if job is None:
            return

        version_id = job.version_id
        if version_id is None:
            raise RuntimeError(f"extract_file job {claim.job_id} has no version_id")

        # A version that already holds this content does not need re-extracting.
        # The case that reaches here is a job that failed before the handler
        # ran (the root was paused, say) while an earlier run had already
        # published the text. Re-reading is harmless for the text itself, but
        # ``persist_chunks`` replaces rows, and replacing chunks for nothing
        # would detach reviews and search indexes that hang off their stable
        # ids. Existing embed jobs keep their own completion/retry policy.
        # If the first dispatch failed after parsing committed, repair that
        # missing job in the same transaction that closes this retry.
        version = db.get(FileVersion, version_id)
        if version is not None and version.status in (
            VersionStatus.BASIC_READY.value,
            VersionStatus.ENRICHED.value,
        ):
            if version.status == VersionStatus.BASIC_READY.value:
                _enqueue_embed_job(db, version_id, first_dispatch_only=True)
            if not _finish(db, claim, status=JobStatus.COMPLETED.value):
                # Roll back the repaired index job too: a stale attempt must not
                # leave work behind that the new owner's transaction does not own.
                db.rollback()
                raise StaleClaim(f"extract job {claim.job_id} moved to another attempt")
            db.commit()
        else:
            source_path = resolve_source_path(db, version_id)
            # B's handler records the document outcome on the version and
            # returns the resulting status; only non-document errors raise.
            status = handle_extract_file(
                db, version_id, source_path, guard=_claim_guard(db, claim)
            )
            # Closing the extract job and dispatching the index job happen in
            # the same transaction, so a crash cannot leave a parsed version
            # unindexed.
            _extract_outcome(db, claim, job, version_id, status)
            db.commit()

    logger.info(
        "extract_finished",
        extra={
            "job_id": claim.job_id,
            "version_id": version_id,
            "job_status": job.status,
            "error_code": job.error_code,
        },
    )


def _process_embed_job(claim: Claim) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, claim.job_id)
        if job is None:
            return

        version_id = job.version_id
        if version_id is None:
            raise RuntimeError(f"embed_file job {claim.job_id} has no version_id")

        # embed_version builds the keyword sidecars first and records an
        # embedding error instead of raising, so a missing model completes
        # the job with keyword-only search.
        result = embed_version(db, version_id, _embedding_backend())
        # ``enriched`` means the text is indexed *and* every chunk carries a
        # vector (contract 8). A keyword-only pass - AI disabled, a model
        # mismatch, a failed batch - stays ``basic_ready`` on purpose, so the
        # model-ready recovery sweep can pick the version up again.
        if (
            result.embedding_error is None
            and result.chunk_count
            and result.embedded_count == result.chunk_count
        ):
            version = db.get(FileVersion, version_id)
            if version is not None and version.status == VersionStatus.BASIC_READY.value:
                version.status = VersionStatus.ENRICHED.value
        # The enriched transition and the job state commit together, and only
        # for the attempt that still owns the row.
        if not _finish(db, claim, status=JobStatus.COMPLETED.value):
            db.rollback()
            raise StaleClaim(f"embed job {claim.job_id} moved to another attempt")
        db.commit()

    logger.info(
        "embed_completed",
        extra={
            "job_id": claim.job_id,
            "version_id": version_id,
            "chunk_count": result.chunk_count,
            "embedded_count": result.embedded_count,
            "embedding_error": result.embedding_error,
        },
    )


def recover_after_model_ready(*, reconcile: bool = True) -> bool:
    """Repair early-scan keyword-only jobs once local inference becomes ready."""
    if not settings.embedding_enabled:
        return False
    try:
        response = httpx.get(
            settings.ai_service_url.rstrip("/") + "/setup", timeout=2,
            follow_redirects=False, trust_env=False,
        )
        response.raise_for_status()
        status = SetupStatus.model_validate(response.json())
    except (httpx.HTTPError, ValueError):
        return False
    if not status.ready or status.state != "ready":
        return False
    if not reconcile:
        return True
    with get_session_factory()() as db:
        count = queue_startup_embeddings(db)
        db.commit()
    if count:
        logger.info("startup_embeddings_queued", extra={"version_count": count})
    return True


def process_job(job_id: int, claim: Claim | None = None) -> None:
    """Route one claimed job to its handler.

    The read-files branches never look up a Case: scan, extract and embed
    jobs target a root or a version, and their case_id is None. Direct callers
    (tests, scripts) may omit the claim; the worker always passes the one it
    took, so a stale attempt is refused at every terminal write.
    """
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job_type = job.job_type
        claim = claim or Claim(job.id, job.attempts, job.lease_owner or LEASE_OWNER)

    if claim.lost:
        raise StaleClaim(f"job {job_id} no longer belongs to attempt {claim.attempts}")

    if job_type == JobType.TRIAGE_CASE.value:
        _process_triage_job(claim)
    elif job_type == RootJobType.SCAN_ROOT.value:
        _process_scan_job(claim)
    elif job_type == RootJobType.EXTRACT_FILE.value:
        _process_extract_job(claim)
    elif job_type == RootJobType.EMBED_FILE.value:
        _process_embed_job(claim)
    else:
        # claim_next_pending_job filters by HANDLED_JOB_TYPES; reaching here
        # means a job type was added to the table without a handler.
        raise RuntimeError(f"no handler for job type {job_type!r}")


class DrainRequest:
    """A signal only requests exit; committed claims must still finish."""

    requested = False

    def request(self, signum=None, frame=None) -> None:
        self.requested = True


def run_worker(*, drain: DrainRequest | None = None) -> None:
    drain = drain or DrainRequest()
    session_factory = get_session_factory()
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "ai_service_url": settings.ai_service_url,
        },
    )

    next_recovery_check = 0.0
    was_model_ready = False
    recovery_until = 0.0
    while not drain.requested:
        claim: Claim | None = None
        try:
            now = time.monotonic()
            if now >= next_recovery_check:
                # A short settling window also catches a pre-ready request that
                # was still completing while the first sweep ran. Afterwards
                # the normal extract->embed dispatcher owns newly parsed files.
                ready = recover_after_model_ready(
                    reconcile=not was_model_ready or now < recovery_until,
                )
                if ready and not was_model_ready:
                    recovery_until = now + 60
                was_model_ready = ready
                next_recovery_check = now + 5
            if drain.requested:
                break
            with session_factory() as db:
                claim = claim_next_pending_job(db)

            # A request arriving inside claim must not strand its committed
            # claimed row. Process that job before checking the flag again.
            if claim is None:
                if not drain.requested:
                    time.sleep(settings.worker_poll_seconds)
                continue

            logger.info("job_claimed", extra={"job_id": claim.job_id})
            # No unconditional release here: a worker that exits before writing
            # a terminal state must leave its deadline intact so the row expires
            # and another worker can recover it. Terminal writes clear the lease
            # in the same guarded statement.
            try:
                with _keep_lease(claim):
                    process_job(claim.job_id, claim)
            except StaleClaim:
                logger.warning("stale_claim_discarded", extra={"job_id": claim.job_id})

        except KeyboardInterrupt:
            logger.info("worker_stopped")
            raise

        except Exception as exc:
            logger.exception("job_processing_failed")
            if claim is not None:
                mark_job_failed(claim.job_id, str(exc), claim=claim)
            if not drain.requested:
                time.sleep(settings.worker_poll_seconds)

    logger.info("worker_drained")


if __name__ == "__main__":
    drain = DrainRequest()
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, drain.request)
    run_worker(drain=drain)
