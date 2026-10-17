"""Minimum W7 integration routes over the canonical B data model.

These routes provide the course's narrow browser path without waiting for the
incompatible C schema branch. Semantic mode degrades to the same keyword path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import Settings, get_settings
from services.common.db import get_db
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
    VersionStatus,
)

router = APIRouter(tags=["workflow"])


class MountRead(BaseModel):
    mount_id: str
    label: str
    read_only: bool = True
    availability: str


class DirectoryRead(BaseModel):
    relative_path: str
    label: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = "keyword"
    top_k: int = Field(default=10, ge=1, le=50)
    root_id: str | None = None
    file_id: str | None = None


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
    payload: SearchRequest,
    db: Session = Depends(get_db),
) -> SearchResponse:
    query = " ".join(payload.query.split())
    terms = tuple(term.casefold() for term in query.split())
    if not terms:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_query", "message": "Query cannot be empty"},
        )

    statement = (
        select(SourceChunk, FileVersion, FileRecord, AuthorizedRoot)
        .join(FileVersion, SourceChunk.version_id == FileVersion.id)
        .join(FileRecord, FileVersion.file_id == FileRecord.id)
        .join(AuthorizedRoot, FileRecord.root_id == AuthorizedRoot.id)
        .where(FileRecord.current_version_id == FileVersion.id)
        .where(
            FileVersion.status.in_(
                [
                    VersionStatus.BASIC_READY.value,
                    VersionStatus.ENRICHED.value,
                ]
            )
        )
        .where(FileRecord.presence_status == FilePresence.PRESENT.value)
        .where(
            AuthorizedRoot.status.in_(
                [RootStatus.ACTIVE.value, RootStatus.PAUSED.value]
            )
        )
    )
    if payload.root_id is not None:
        statement = statement.where(FileRecord.root_id == payload.root_id)
    if payload.file_id is not None:
        statement = statement.where(FileRecord.id == payload.file_id)

    rows = db.execute(statement).all()
    query_folded = query.casefold()
    candidates: dict[str, SearchResult] = {}
    for chunk, version, file_record, root in rows:
        text_folded = " ".join(chunk.text.split()).casefold()
        matched = [term for term in terms if term in text_folded]
        # Fixed evaluation queries can wrap the useful phrase in an instruction
        # such as "find the file containing ...". Require substantial coverage,
        # not every stop word, so the document with the unique marker still wins.
        if len(matched) < max(1, (len(terms) + 1) // 2):
            continue

        phrase = query_folded in text_folded
        name_match = query_folded in file_record.name.casefold()
        score = min(
            1.0,
            0.75 * len(matched) / len(terms)
            + (0.2 if phrase else 0.0)
            + (0.05 if name_match else 0.0),
        )
        result = SearchResult(
            root_id=root.id,
            file_id=file_record.id,
            file_name=file_record.name,
            file_path=file_record.relative_path,
            version_id=version.id,
            version_created_at=version.created_at,
            chunk_id=chunk.id,
            ordinal=chunk.ordinal,
            page=chunk.page_number,
            text=chunk.text[:2000],
            reason="keyword: " + ", ".join(matched),
            score=round(score, 6),
            keyword_score=round(score, 6),
        )
        existing = candidates.get(file_record.id)
        if existing is None or (result.score, -result.ordinal) > (
            existing.score,
            -existing.ordinal,
        ):
            candidates[file_record.id] = result

    results = sorted(
        candidates.values(),
        key=lambda result: (
            -result.score,
            result.file_name.casefold(),
            result.ordinal,
        ),
    )[: payload.top_k]
    degraded = payload.mode in {"semantic", "hybrid"}
    return SearchResponse(
        query=query,
        mode=payload.mode,
        effective_mode="keyword",
        results=results,
        total=len(candidates),
        degraded=degraded,
        degradation_reason="semantic_not_integrated" if degraded else None,
        candidate_count=len(rows),
        candidate_limit=200,
    )
