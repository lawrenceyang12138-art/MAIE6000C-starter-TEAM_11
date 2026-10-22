from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.common.config import Settings, configure_logging, get_settings
from services.common.db import get_db
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
    RootStatus,
    VersionStatus,
)
from services.common.schemas import (
    CaseCreate,
    CaseCreateResponse,
    CaseRead,
    DirectoryRead,
    HealthResponse,
    JobRead,
    JobRetryAccepted,
    MountRead,
    RootCreate,
    RootFileCounts,
    RootJobAccepted,
    RootRead,
    SearchRequest,
    SearchResponse,
)
from services.api.app.errors import reason
from services.api.app.parsing_routes import router as parsing_router
from services.search.embeddings import EmbeddingBackend, HTTPEmbeddingBackend
from services.search.retrieval import search_chunks

configure_logging()
logger = logging.getLogger("services.api.main")

app = FastAPI(title="MAIE 6000C Starter API", version="0.1.0")
app.include_router(parsing_router)

HTTP_REQUESTS = Counter(
    "api_http_requests_total",
    "Total API HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_LATENCY = Histogram(
    "api_http_request_duration_seconds",
    "API request duration in seconds",
    ["method", "path"],
)
CASES_CREATED = Counter("api_cases_created_total", "Total cases created")
SEARCH_REQUESTS = Counter("api_search_requests_total", "Search requests", ["mode", "degraded"])

# Display labels for configured mounts. A label is presentation only: the
# allowlist itself stays in settings, and an unlabelled mount falls back to its
# id so a new mount never breaks the picker.
MOUNT_LABELS = {"corpus": "Course corpus"}

# Database job states that are public API states are identical; ``claimed`` is
# the one exception (contract 8-A.7).
_PUBLIC_JOB_STATUS = {JobStatus.CLAIMED.value: "running"}

_LIVE_JOB_STATUSES = [JobStatus.PENDING.value, JobStatus.CLAIMED.value]


def public_job_status(status: str) -> str:
    return _PUBLIC_JOB_STATUS.get(status, status)


def to_job_read(job: Job) -> JobRead:
    """Present one job without leaking database-only states or error text."""
    return JobRead(
        job_id=job.id,
        case_id=job.case_id,
        root_id=job.root_id,
        version_id=job.version_id,
        job_type=job.job_type,
        status=public_job_status(job.status),
        attempts=job.attempts,
        # The stored `error` is a diagnostic string; only a stable code leaves
        # the service (privacy rule: no stack traces to the browser).
        error_code="job_failed" if job.error else None,
        created_at=job.created_at,
        claimed_at=job.claimed_at,
        completed_at=job.completed_at,
    )


def get_embedding_backend(settings: Settings = Depends(get_settings)) -> EmbeddingBackend | None:
    if not settings.embedding_enabled:
        return None
    return HTTPEmbeddingBackend(settings.ai_service_url, settings.search_request_timeout_seconds)


def create_case_with_job(db: Session, payload: CaseCreate) -> tuple[Case, Job]:
    case = Case(
        title=payload.title.strip(),
        description=payload.description.strip(),
        status=CaseStatus.QUEUED.value,
    )
    db.add(case)
    db.flush()

    job = Job(
        case_id=case.id,
        job_type=JobType.TRIAGE_CASE.value,
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    db.commit()
    db.refresh(case)
    db.refresh(job)
    return case, job


def list_cases(db: Session, limit: int) -> list[Case]:
    stmt = select(Case).order_by(Case.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()


def get_case(db: Session, case_id: str) -> Case | None:
    return db.get(Case, case_id)


def get_job(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def normalise_relative_path(relative_path: str) -> str:
    """Reject anything that would escape the allowed mount.

    The browser sends a path relative to a configured mount, never an absolute
    host path, so a leading slash or any ``..`` segment is a rejected request.
    """
    cleaned = relative_path.strip().replace("\\", "/")
    if cleaned.startswith("/"):
        raise HTTPException(
            status_code=403,
            detail=reason(
                "path_out_of_scope", "Path must be relative to the configured mount"
            ),
        )

    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise HTTPException(
            status_code=403,
            detail=reason("path_out_of_scope", "Path escapes the allowed mount"),
        )
    return "/".join(parts) or "."


def _lock_root(db: Session, root_id: str) -> AuthorizedRoot | None:
    """Read one root under a row lock, refreshed from the database.

    Every queue decision for a root - lifecycle check, live-job check, enqueue -
    runs while holding this lock, so two concurrent requests cannot both observe
    "no live scan" and both queue one. PostgreSQL honours ``FOR UPDATE``; SQLite
    ignores the clause but serialises writers anyway, so the route tests still
    exercise the sequential path and a PostgreSQL test covers the interleaving.
    """
    return db.execute(
        select(AuthorizedRoot)
        .where(AuthorizedRoot.id == root_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().first()


def _ensure_active_root(root: AuthorizedRoot) -> None:
    """Refuse new work for any root that is not active (contract 3.1).

    Paused roots accept no new jobs, revoking roots accept only cleanup work and
    revoked roots accept nothing. Each state gets its own code so a client can
    tell "resume it" apart from "authorize it again".
    """
    if root.status == RootStatus.ACTIVE.value:
        return
    if root.status == RootStatus.PAUSED.value:
        raise HTTPException(
            status_code=409,
            detail=reason("root_paused", "This directory is paused; resume it first"),
        )
    if root.status == RootStatus.REVOKING.value:
        raise HTTPException(
            status_code=409,
            detail=reason(
                "root_revoking",
                "This directory is being revoked and accepts no new work",
            ),
        )
    raise HTTPException(
        status_code=409,
        detail=reason(
            "root_revoked", "This directory authorization is no longer active"
        ),
    )


def _active_scan_job(db: Session, root_id: str) -> Job | None:
    """The live scan for one root, if any.

    Pending and claimed both count: claiming happens in the worker, and a scan
    already claimed must not be queued a second time.
    """
    return db.execute(
        select(Job)
        .where(
            Job.root_id == root_id,
            Job.job_type == RootJobType.SCAN_ROOT.value,
            Job.status.in_(_LIVE_JOB_STATUSES),
        )
        .limit(1)
    ).scalars().first()


def _scan_conflict(root_id: str, active: Job, where: str) -> HTTPException:
    """409 for a live scan, carrying the ids contract 6.2 asks for.

    A client whose first request timed out can use ``root_id``/``job_id`` to
    attach to the work already accepted instead of submitting again.
    """
    return HTTPException(
        status_code=409,
        detail=reason(
            "active_job_exists",
            f"A scan is already active for this root ({where})",
            root_id=root_id,
            job_id=active.id,
        ),
    )


def _enqueue_scan(db: Session, root: AuthorizedRoot) -> Job:
    job = Job(
        root_id=root.id,
        job_type=RootJobType.SCAN_ROOT.value,
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _find_root(
    db: Session, mount_id: str, relative_path: str
) -> AuthorizedRoot | None:
    return db.execute(
        select(AuthorizedRoot).where(
            AuthorizedRoot.mount_id == mount_id,
            AuthorizedRoot.relative_path == relative_path,
        )
    ).scalars().first()


def create_root_with_scan_job(
    db: Session, mount_id: str, relative_path: str
) -> tuple[AuthorizedRoot, Job]:
    """Authorize a folder and enqueue its first scan (contract 6.2).

    Idempotent on (mount_id, relative_path): the same folder is never
    authorized twice. Re-posting while its scan is live is refused with
    ``409 active_job_exists`` plus the existing ids; with nothing running, a new
    scan is queued. Both decisions run under the root row lock, so concurrent
    re-posts cannot queue two scans for one folder.
    """
    existing = _find_root(db, mount_id, relative_path)
    if existing is None:
        root = AuthorizedRoot(
            mount_id=mount_id,
            relative_path=relative_path,
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        try:
            db.flush()
        except IntegrityError:
            # Another request authorized the same folder between our read and
            # our insert. Fall through to the shared path so it decides.
            db.rollback()
            existing = _find_root(db, mount_id, relative_path)
            if existing is None:
                raise
        else:
            job = Job(
                root_id=root.id,
                job_type=RootJobType.SCAN_ROOT.value,
                status=JobStatus.PENDING.value,
            )
            db.add(job)
            db.commit()
            db.refresh(root)
            db.refresh(job)
            return root, job

    root = _lock_root(db, existing.id)
    if root is None:
        raise HTTPException(
            status_code=404, detail=reason("root_not_found", "Root not found")
        )
    _ensure_active_root(root)
    active = _active_scan_job(db, root.id)
    if active is not None:
        raise _scan_conflict(root.id, active, "same folder")
    return root, _enqueue_scan(db, root)


def read_root_counts(db: Session, root_id: str) -> RootFileCounts:
    """Count the current versions of one root by stage (contract 6.2).

    One row per current version, grouped by status. A file that has no current
    version counts as ``discovered``; historical versions are never counted, so
    the buckets stay mutually exclusive and sum to ``total``.
    """
    rows = db.execute(
        select(FileVersion.status, func.count())
        .select_from(FileRecord)
        .outerjoin(FileVersion, FileVersion.id == FileRecord.current_version_id)
        .where(FileRecord.root_id == root_id)
        .group_by(FileVersion.status)
    ).all()

    buckets: dict[str, int] = {stage.value: 0 for stage in VersionStatus}
    total = 0
    for status, count in rows:
        stage = status if status in buckets else VersionStatus.DISCOVERED.value
        buckets[stage] += int(count)
        total += int(count)
    return RootFileCounts(total=total, **buckets)


def root_availability(root: AuthorizedRoot) -> str:
    """Whether the authorized directory is readable right now.

    Availability is derived, not stored: the mount may be unmounted or the
    folder renamed between requests, and a stored flag would lie. An unknown
    mount id can only appear if the allowlist changed after authorization.
    """
    mount_path = get_settings().source_mounts.get(root.mount_id)
    if mount_path is None:
        return "unavailable"
    base = Path(mount_path)
    target = base if root.relative_path in ("", ".") else base / root.relative_path
    try:
        return "available" if target.is_dir() else "unavailable"
    except OSError:
        return "unavailable"


def to_root_read(db: Session, root: AuthorizedRoot) -> RootRead:
    return RootRead(
        root_id=root.id,
        mount_id=root.mount_id,
        relative_path=root.relative_path,
        status=RootStatus(root.status),
        availability=root_availability(root),
        file_counts=read_root_counts(db, root.id),
        last_successful_scan_at=root.last_successful_scan_at,
    )


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    start = perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration = perf_counter() - start
        path = request.url.path
        status = str(response.status_code) if response is not None else "500"
        HTTP_REQUESTS.labels(request.method, path, status).inc()
        HTTP_REQUEST_LATENCY.labels(request.method, path).observe(duration)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": path,
                "status_code": status,
                "duration_seconds": round(duration, 4),
            },
        )


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(service="api", status="ok")


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(service="api", status="ok")


@app.get("/health/ready", response_model=HealthResponse)
def health_ready(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(service="api", status="ok")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/cases", response_model=CaseCreateResponse, status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)) -> CaseCreateResponse:
    case, job = create_case_with_job(db, payload)
    CASES_CREATED.inc()
    logger.info("case_created", extra={"case_id": case.id, "job_id": job.id})
    return CaseCreateResponse(
        case=CaseRead.model_validate(case),
        job=to_job_read(job),
    )


@app.get("/cases", response_model=list[CaseRead])
def read_cases(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CaseRead]:
    return [CaseRead.model_validate(case) for case in list_cases(db, limit)]


@app.get("/cases/{case_id}", response_model=CaseRead)
def read_case(case_id: str, db: Session = Depends(get_db)) -> CaseRead:
    case = get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseRead.model_validate(case)


@app.get("/jobs/{job_id}", response_model=JobRead)
def read_job(job_id: int, db: Session = Depends(get_db)) -> JobRead:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=reason("job_not_found", "Job not found")
        )
    return to_job_read(job)


def _live_job_for_target(db: Session, job: Job) -> Job | None:
    """Another live job aimed at the same target, which blocks a retry.

    Retrying must not create a second worker for the same file version or the
    same root; the target columns are mutually exclusive by construction.
    """
    stmt = select(Job).where(
        Job.job_type == job.job_type,
        Job.status.in_(_LIVE_JOB_STATUSES),
        Job.id != job.id,
    )
    if job.version_id is not None:
        stmt = stmt.where(Job.version_id == job.version_id)
    elif job.root_id is not None:
        stmt = stmt.where(Job.root_id == job.root_id)
    else:
        stmt = stmt.where(Job.case_id == job.case_id)
    return db.execute(stmt.limit(1)).scalars().first()


def _root_for_job(db: Session, job: Job) -> AuthorizedRoot | None:
    """The root a job belongs to, following the version when necessary.

    Scan and extract jobs carry ``root_id`` directly, but embed jobs created by
    the worker carry only ``version_id``; without that fallback an embed retry
    would skip the root lifecycle check entirely.
    """
    if job.root_id is not None:
        return db.get(AuthorizedRoot, job.root_id)
    if job.version_id is None:
        return None
    version = db.get(FileVersion, job.version_id)
    if version is None:
        return None
    record = db.get(FileRecord, version.file_id)
    if record is None:
        return None
    return db.get(AuthorizedRoot, record.root_id)


@app.post("/jobs/{job_id}/retry", response_model=JobRetryAccepted, status_code=202)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobRetryAccepted:
    """Put a failed job back on the queue (contract 6.3).

    Only ``failed`` jobs are retryable: a completed job has nothing to redo, and
    a pending one is already queued. The attempt count is kept as provenance;
    the recorded error is cleared because the next run starts fresh.

    Retrying is new work, so the owning root must be active (contract 3.1). The
    root row is locked before the live-job check and the state transition, so
    two concurrent retries cannot both requeue, and a retry cannot slip in while
    a revoke is being applied.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=reason("job_not_found", "Job not found")
        )
    if job.status != JobStatus.FAILED.value:
        raise HTTPException(
            status_code=409,
            detail=reason(
                "job_not_retryable",
                f"Only failed jobs can be retried; this job is {public_job_status(job.status)}",
            ),
        )

    root = _root_for_job(db, job)
    if root is not None:
        root = _lock_root(db, root.id) or root
        _ensure_active_root(root)

    blocked = _live_job_for_target(db, job)
    if blocked is not None:
        raise HTTPException(
            status_code=409,
            detail=reason(
                "active_job_exists",
                f"Another job ({blocked.id}) is already working on this target",
                root_id=root.id if root is not None else None,
                job_id=blocked.id,
            ),
        )

    job.status = JobStatus.PENDING.value
    job.error = None
    job.claimed_at = None
    job.completed_at = None
    db.commit()
    db.refresh(job)

    logger.info("job_retry_queued", extra={"job_id": job.id, "job_type": job.job_type})
    return JobRetryAccepted(
        job_id=job.id,
        root_id=job.root_id,
        status=public_job_status(job.status),
    )


@app.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    backend: EmbeddingBackend | None = Depends(get_embedding_backend),
) -> SearchResponse:
    result = search_chunks(db, payload, settings, backend)
    SEARCH_REQUESTS.labels(payload.mode.value, str(result.degraded).lower()).inc()
    logger.info(
        "search_completed",
        extra={
            "mode": payload.mode.value,
            "effective_mode": result.effective_mode.value,
            "result_count": len(result.results),
            "degradation_reason": result.degradation_reason,
        },
    )
    return result


def _mount_path(mount_id: str) -> Path:
    """Container path of a configured mount, or ``404 unknown_mount``."""
    mounts = get_settings().source_mounts
    if mount_id not in mounts:
        raise HTTPException(
            status_code=404,
            detail=reason("unknown_mount", f"Unknown mount_id: {mount_id!r}"),
        )
    return Path(mounts[mount_id])


def _contained_mount_dir(mount_id: str, relative_path: str) -> Path:
    """Resolve a relative directory inside its mount and enforce containment.

    ``resolve()`` collapses symlinks, so a link pointing outside the mount is
    rejected rather than listed: a read-only mount alone is not authorization.
    """
    base = _mount_path(mount_id).resolve()
    rel = normalise_relative_path(relative_path)
    candidate = base if rel == "." else (base / rel).resolve()
    if candidate != base and base not in candidate.parents:
        raise HTTPException(
            status_code=403,
            detail=reason("path_out_of_scope", "Path escapes the allowed mount"),
        )
    return candidate


@app.get("/mounts", response_model=list[MountRead])
def list_mounts() -> list[MountRead]:
    """Configured read-only mounts the folder picker may offer."""
    return [
        MountRead(
            mount_id=mount_id,
            label=MOUNT_LABELS.get(mount_id, mount_id),
            # Mounts are bind-mounted read-only in compose; the API never
            # writes to them, so this is a statement about the deployment.
            read_only=True,
            availability="available" if Path(path).is_dir() else "unavailable",
        )
        for mount_id, path in get_settings().source_mounts.items()
    ]


@app.get("/mounts/{mount_id}/directories", response_model=list[DirectoryRead])
def list_mount_directories(
    mount_id: str,
    relative_path: str = Query(default=".", max_length=500),
) -> list[DirectoryRead]:
    """Immediate subdirectories of one folder inside a mount.

    The first entry is the requested folder itself, so the caller can show
    "this folder" next to its children. Hidden entries and symlinked
    directories are skipped; both would either confuse the picker or escape the
    authorized tree.
    """
    base = _contained_mount_dir(mount_id, relative_path)
    if not base.is_dir():
        raise HTTPException(
            status_code=404,
            detail=reason("source_unavailable", "The selected directory is not available"),
        )

    rel = normalise_relative_path(relative_path)
    entries = [
        DirectoryRead(
            relative_path=rel,
            label=MOUNT_LABELS.get(mount_id, mount_id) if rel == "." else base.name,
        )
    ]
    for child in sorted(base.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        entries.append(
            DirectoryRead(
                relative_path=child.relative_to(_mount_path(mount_id)).as_posix(),
                label=child.name,
            )
        )
    return entries


@app.post("/roots", response_model=RootJobAccepted, status_code=202)
def create_root(payload: RootCreate, db: Session = Depends(get_db)) -> RootJobAccepted:
    """Authorize a folder and start its first scan.

    Returns 202 with the ids before discovery or analysis finishes. The worker
    owns everything slow; this endpoint only validates and records intent.
    """
    mount_id = payload.mount_id.strip()
    if mount_id not in get_settings().source_mounts:
        # D3: an unknown mount_id is not in the allowlist at all, which is a
        # missing resource (404 unknown_mount), not an out-of-scope path (403).
        raise HTTPException(
            status_code=404,
            detail=reason("unknown_mount", f"Unknown mount_id: {mount_id!r}"),
        )
    relative_path = normalise_relative_path(payload.relative_path)

    root, job = create_root_with_scan_job(db, mount_id, relative_path)

    logger.info(
        "root_authorized",
        extra={"root_id": root.id, "job_id": job.id, "mount_id": mount_id},
    )

    return RootJobAccepted(
        root_id=root.id,
        job_id=job.id,
        status=public_job_status(job.status),
    )


@app.get("/roots", response_model=list[RootRead])
def list_roots(db: Session = Depends(get_db)) -> list[RootRead]:
    """Authorized folders that have not been revoked.

    The UI restores its folder list from here after a reload; revoked roots are
    history and need an explicit query (contract 6.2).
    """
    roots = db.execute(
        select(AuthorizedRoot)
        .where(AuthorizedRoot.status != RootStatus.REVOKED.value)
        .order_by(AuthorizedRoot.created_at.desc())
    ).scalars().all()
    return [to_root_read(db, root) for root in roots]


@app.get("/roots/{root_id}", response_model=RootRead)
def read_root(root_id: str, db: Session = Depends(get_db)) -> RootRead:
    """Read one authorized folder's status and current-version counts."""
    root = db.get(AuthorizedRoot, root_id)
    if root is None:
        raise HTTPException(
            status_code=404, detail=reason("root_not_found", "Root not found")
        )
    return to_root_read(db, root)


@app.post("/roots/{root_id}/scans", response_model=RootJobAccepted, status_code=202)
def rescan_root(root_id: str, db: Session = Depends(get_db)) -> RootJobAccepted:
    """Queue another scan of an existing root.

    Authorization and the first scan stay atomic in ``POST /roots``; this route
    only re-runs discovery for a folder that is already authorized.
    """
    root = _lock_root(db, root_id)
    if root is None:
        raise HTTPException(
            status_code=404, detail=reason("root_not_found", "Root not found")
        )
    _ensure_active_root(root)

    active = _active_scan_job(db, root.id)
    if active is not None:
        raise _scan_conflict(root.id, active, "rescan")

    job = _enqueue_scan(db, root)
    logger.info("root_rescan_queued", extra={"root_id": root.id, "job_id": job.id})
    return RootJobAccepted(
        root_id=root.id,
        job_id=job.id,
        status=public_job_status(job.status),
    )
