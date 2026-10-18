from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.common.models import CaseStatus, JobStatus, RootStatus


class HealthResponse(BaseModel):
    service: str
    status: str


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=4000)


class CaseRead(BaseModel):
    id: str
    title: str
    description: str
    status: CaseStatus
    ai_label: str | None = None
    ai_summary: str | None = None
    ai_confidence: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobRead(BaseModel):
    id: int
    case_id: str | None = None
    root_id: str | None = None
    version_id: str | None = None
    # Jobs are general now: the starter's triage_case, plus scan_root and
    # extract_file. Kept as a plain string rather than a single enum.
    job_type: str
    status: JobStatus
    attempts: int
    error: str | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RootCreate(BaseModel):
    """Authorize a folder and start its first scan.

    relative_path is resolved inside the configured mount, never treated as an
    arbitrary host path.
    """

    mount_id: str = Field(min_length=1, max_length=100)
    relative_path: str = Field(min_length=1, max_length=500)


class RootRead(BaseModel):
    id: str
    mount_id: str
    relative_path: str
    status: RootStatus
    file_count: int = 0
    indexed_count: int = 0
    last_successful_scan_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RootCreateResponse(BaseModel):
    root: RootRead
    job: JobRead


class CaseCreateResponse(BaseModel):
    case: CaseRead
    job: JobRead


class TriageRequest(BaseModel):
    case_id: str
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=4000)


class TriageResponse(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    summary: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
