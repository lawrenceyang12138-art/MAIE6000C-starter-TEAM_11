"""Minimum W7 integration routes over the canonical B data model.

These routes provide the course's narrow browser path without waiting for the
incompatible C schema branch. Semantic mode degrades to the same keyword path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.common.config import Settings, get_settings
from services.common.db import get_db
from services.common.schemas import SearchQuery
from services.search.embeddings import EmbeddingBackend, HTTPEmbeddingBackend
from services.search.retrieval import search_chunks as search_canonical_chunks

router = APIRouter(tags=["workflow"])


def get_embedding_backend(
    settings: Settings = Depends(get_settings),
) -> EmbeddingBackend | None:
    if not settings.embedding_enabled:
        return None
    return HTTPEmbeddingBackend(
        settings.ai_service_url,
        settings.search_request_timeout_seconds,
    )


class MountRead(BaseModel):
    mount_id: str
    label: str
    read_only: bool = True
    availability: str


class DirectoryRead(BaseModel):
    relative_path: str
    label: str


class SearchResult(BaseModel):
    root_id: str
    file_id: str
    file_name: str
    file_path: str
    version_id: str
    version_created_at: datetime
    chunk_id: str
    ordinal: int
    page: int | None
    text: str
    reason: str
    score: float
    keyword_score: float
    semantic_score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    mode: str
    effective_mode: str
    results: list[SearchResult]
    total: int
    degraded: bool
    degradation_reason: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    candidate_count: int
    candidate_limit: int


@router.get("/mounts", response_model=list[MountRead])
def list_mounts(settings: Settings = Depends(get_settings)) -> list[MountRead]:
    return [
        MountRead(
            mount_id=mount_id,
            label=mount_id,
            availability=(
                "available" if Path(path).is_dir() else "unavailable"
            ),
        )
        for mount_id, path in settings.source_mounts.items()
    ]


@router.get(
    "/mounts/{mount_id}/directories",
    response_model=list[DirectoryRead],
)
def list_directories(
    mount_id: str,
    settings: Settings = Depends(get_settings),
) -> list[DirectoryRead]:
    configured = settings.source_mounts.get(mount_id)
    if configured is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_mount", "message": "No such mount"},
        )
    base = Path(configured).resolve()
    if not base.is_dir():
        raise HTTPException(
            status_code=503,
            detail={"code": "mount_unavailable", "message": "Mount is unavailable"},
        )

    directories = [
        DirectoryRead(relative_path=".", label=mount_id),
    ]
    for entry in sorted(base.iterdir(), key=lambda value: value.name.casefold()):
        if (
            entry.is_dir()
            and not entry.is_symlink()
            and not entry.name.startswith(".")
        ):
            directories.append(
                DirectoryRead(relative_path=entry.name, label=entry.name)
            )
    return directories


@router.post("/search", response_model=SearchResponse)
def search_chunks(
    payload: SearchQuery,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    backend: EmbeddingBackend | None = Depends(get_embedding_backend),
) -> SearchResponse:
    result = search_canonical_chunks(
        db,
        query=payload.query,
        mode=payload.mode,
        top_k=payload.top_k,
        root_id=payload.root_id,
        file_id=payload.file_id,
        settings=settings,
        backend=backend,
    )
    return SearchResponse(
        query=payload.query,
        mode=payload.mode,
        effective_mode=result.effective_mode,
        results=[
            SearchResult(
                root_id=hit.root_id,
                file_id=hit.file_id,
                file_name=hit.file_name,
                file_path=hit.file_path,
                version_id=hit.version_id,
                version_created_at=hit.version_created_at,
                chunk_id=hit.chunk_id,
                ordinal=hit.ordinal,
                page=hit.page,
                text=hit.text,
                reason=hit.reason,
                score=hit.score,
                keyword_score=hit.keyword_score,
                semantic_score=hit.semantic_score,
            )
            for hit in result.results
        ],
        total=result.total,
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        embedding_model=result.embedding_model,
        embedding_dimensions=result.embedding_dimensions,
        candidate_count=result.candidate_count,
        candidate_limit=result.candidate_limit,
    )
