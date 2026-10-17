from __future__ import annotations

import logging
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.common.config import configure_logging
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
    utcnow,
)
from services.common.schemas import (
    CaseCreate,
    CaseCreateResponse,
    CaseRead,
    HealthResponse,
    JobRead,
    RootCreate,
    RootCreateResponse,
    RootFileCounts,
    RootRead,
)
from services.api.app.parsing_routes import router as parsing_router
from services.api.app.integration_routes import router as integration_router

configure_logging()
logger = logging.getLogger("services.api.main")

app = FastAPI(title="MAIE 6000C Starter API", version="0.1.0")
app.include_router(parsing_router)
app.include_router(integration_router)

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
            status_code=403, detail="Path must be relative to the configured mount"
        )

    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise HTTPException(
            status_code=403, detail="Path escapes the allowed mount"
        )
    return "/".join(parts) or "."


def create_root_with_scan_job(
    db: Session, mount_id: str, relative_path: str
) -> tuple[AuthorizedRoot, Job]:
    """Authorize a folder and enqueue its first scan.

    Idempotent on (mount_id, relative_path): re-posting the same folder returns
    the existing root and its most recent job instead of authorizing it twice.
    """
    existing = (
        db.execute(
            select(AuthorizedRoot).where(
                AuthorizedRoot.mount_id == mount_id,
                AuthorizedRoot.relative_path == relative_path,
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        active_job = (
            db.execute(
                select(Job)
                .where(
                    Job.root_id == existing.id,
                    Job.job_type == RootJobType.SCAN_ROOT.value,
                    Job.status.in_(
                        [
                            JobStatus.PENDING.value,
                            JobStatus.CLAIMED.value,
                            JobStatus.RETRY_WAIT.value,
                        ]
                    ),
                )
                .order_by(Job.created_at.desc())
            )
            .scalars()
            .first()
        )
        if active_job is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "active_job_exists",
                    "message": "A scan is already active for this root",
                },
            )
        job = Job(
            root_id=existing.id,
            job_type=RootJobType.SCAN_ROOT.value,
            status=JobStatus.PENDING.value,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return existing, job

    root = AuthorizedRoot(
        mount_id=mount_id,
        relative_path=relative_path,
        status=RootStatus.ACTIVE.value,
    )
    db.add(root)
    db.flush()

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


def read_root_counts(db: Session, root_id: str) -> RootFileCounts:
    files = db.execute(
        select(FileRecord).where(FileRecord.root_id == root_id)
    ).scalars().all()
    counts = {
        "total": len(files),
        "discovered": 0,
        "extracting": 0,
        "basic_ready": 0,
        "enriched": 0,
        "failed": 0,
        "unsupported": 0,
    }
    for file_record in files:
        version = (
            db.get(FileVersion, file_record.current_version_id)
            if file_record.current_version_id is not None
            else None
        )
        status = version.status if version is not None else "discovered"
        if status in counts:
            counts[status] += 1
    return RootFileCounts(**counts)


def to_root_read(db: Session, root: AuthorizedRoot) -> RootRead:
    file_counts = read_root_counts(db, root.id)
    return RootRead(
        root_id=root.id,
        mount_id=root.mount_id,
        relative_path=root.relative_path,
        status=RootStatus(root.status),
        availability=(
            "available"
            if root.status in {RootStatus.ACTIVE.value, RootStatus.PAUSED.value}
            else "unavailable"
        ),
        file_counts=file_counts,
        last_successful_scan_at=root.last_successful_scan_at,
        created_at=root.created_at,
        updated_at=root.updated_at,
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
        job=JobRead.model_validate(job),
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
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead.model_validate(job)


@app.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobRead:
    """Explicitly requeue a failed job without replaying its old result.

    The worker still owns processing. The client may only ask for a retry; it
    cannot set a job to running or completed. ``attempts`` is intentionally
    retained so the retry history remains visible.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.FAILED.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_retryable",
                "message": "Only a failed job can be retried",
            },
        )
    job.status = JobStatus.PENDING.value
    job.error = None
    job.claimed_at = None
    job.available_at = utcnow()
    job.lease_expires_at = None
    job.worker_id = None
    job.completed_at = None
    db.commit()
    db.refresh(job)
    logger.info("job_retried", extra={"job_id": job.id})
    return JobRead.model_validate(job)


@app.post("/roots", response_model=RootCreateResponse, status_code=202)
def create_root(
    payload: RootCreate, db: Session = Depends(get_db)
) -> RootCreateResponse:
    """Authorize a folder and start its first scan.

    Returns 202 with the ids before discovery or analysis finishes. The worker
    owns everything slow; this endpoint only validates and records intent.
    """
    mount_id = payload.mount_id.strip()
    relative_path = normalise_relative_path(payload.relative_path)

    root, job = create_root_with_scan_job(db, mount_id, relative_path)

    logger.info(
        "root_authorized",
        extra={"root_id": root.id, "job_id": job.id, "mount_id": mount_id},
    )

    public_job = JobRead.model_validate(job)
    return RootCreateResponse(
        root_id=root.id,
        job_id=public_job.job_id,
        status=public_job.status,
    )


@app.get("/roots", response_model=list[RootRead])
def read_roots(db: Session = Depends(get_db)) -> list[RootRead]:
    roots = db.execute(
        select(AuthorizedRoot)
        .where(AuthorizedRoot.status != RootStatus.REVOKED.value)
        .order_by(AuthorizedRoot.created_at.desc())
    ).scalars().all()
    return [to_root_read(db, root) for root in roots]


@app.get("/roots/{root_id}", response_model=RootRead)
def read_root(root_id: str, db: Session = Depends(get_db)) -> RootRead:
    """Read one authorized folder's status and indexed counts."""
    root = db.get(AuthorizedRoot, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Root not found")
    return to_root_read(db, root)
