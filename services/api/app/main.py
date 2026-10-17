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
from sqlalchemy import func, select, text
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
    HealthResponse,
    JobRead,
    SearchRequest,
    SearchResponse,
    RootCreate,
    RootCreateResponse,
    RootRead,
)
from services.search.embeddings import EmbeddingBackend, HTTPEmbeddingBackend
from services.search.retrieval import search_chunks

configure_logging()
logger = logging.getLogger("services.api.main")

app = FastAPI(title="MAIE 6000C Starter API", version="0.1.0")

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
        job = (
            db.execute(
                select(Job)
                .where(Job.root_id == existing.id)
                .order_by(Job.created_at.desc())
            )
            .scalars()
            .first()
        )
        if job is None:
            raise HTTPException(
                status_code=409, detail="Root exists but has no scan job"
            )
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


def read_root_counts(db: Session, root_id: str) -> tuple[int, int]:
    file_count = db.execute(
        select(func.count())
        .select_from(FileRecord)
        .where(FileRecord.root_id == root_id)
    ).scalar_one()

    indexed_count = db.execute(
        select(func.count())
        .select_from(FileVersion)
        .join(FileRecord, FileVersion.file_id == FileRecord.id)
        .where(FileRecord.root_id == root_id)
        .where(
            FileVersion.status.in_(
                [VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value]
            )
        )
    ).scalar_one()

    return int(file_count), int(indexed_count)


def to_root_read(db: Session, root: AuthorizedRoot) -> RootRead:
    file_count, indexed_count = read_root_counts(db, root.id)
    return RootRead(
        id=root.id,
        mount_id=root.mount_id,
        relative_path=root.relative_path,
        status=RootStatus(root.status),
        file_count=file_count,
        indexed_count=indexed_count,
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

    return RootCreateResponse(
        root=to_root_read(db, root),
        job=JobRead.model_validate(job),
    )


@app.get("/roots/{root_id}", response_model=RootRead)
def read_root(root_id: str, db: Session = Depends(get_db)) -> RootRead:
    """Read one authorized folder's status and indexed counts."""
    root = db.get(AuthorizedRoot, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Root not found")
    return to_root_read(db, root)
