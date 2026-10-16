from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.common.models import CaseStatus, JobStatus, JobType
from services.search.text import MAX_QUERY_TOKENS, tokenize


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
    case_id: str
    job_type: JobType
    status: JobStatus
    attempts: int
    error: str | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


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


class SearchMode(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=50)
    file_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query must contain at least one non-whitespace character")
        if len(tokenize(normalized)) > MAX_QUERY_TOKENS:
            raise ValueError(f"query must contain at most {MAX_QUERY_TOKENS} searchable tokens")
        return normalized


class SearchResultRead(BaseModel):
    file_id: str
    file_name: str
    file_path: str
    version_id: str
    version_number: int
    chunk_id: str
    chunk_index: int
    page_start: int
    page_end: int
    text: str
    reason: str
    score: float = Field(ge=0.0, le=1.0)
    keyword_score: float = Field(ge=0.0, le=1.0)
    semantic_score: float = Field(ge=0.0, le=1.0)


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    effective_mode: SearchMode
    results: list[SearchResultRead]
    total: int = Field(ge=0, description="Distinct matching files in the bounded candidate pool")
    degraded: bool = False
    degradation_reason: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    candidate_count: int = Field(default=0, ge=0)
    candidate_limit: int = Field(default=200, ge=1, description="Candidate file limit per channel")


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=16)
    kind: Literal["query", "passage"] = "passage"

    @field_validator("texts")
    @classmethod
    def validate_texts(cls, values: list[str]) -> list[str]:
        if any(not text.strip() or len(text) > 2000 for text in values):
            raise ValueError("texts must contain between 1 and 2000 characters each")
        return values


class EmbeddingResponse(BaseModel):
    model: str
    dimensions: int = Field(gt=0)
    vectors: list[list[float]]
