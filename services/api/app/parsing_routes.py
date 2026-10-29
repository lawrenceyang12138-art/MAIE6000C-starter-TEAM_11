"""HTTP boundary for B's parsing, evidence, relation and review handlers.

The handlers remain independently testable; this router only maps transport
details and stable reason codes to HTTP.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.errors import reason
from services.common.db import get_db
from services.common.models import AuthorizedRoot, FileRecord, FileVersion, RootStatus
from services.parsing.evidence import (
    REASON_CHUNK_NOT_FOUND,
    REASON_FILE_MISSING,
    REASON_NO_CURRENT_VERSION,
    REASON_ROOT_REVOKED,
    REASON_VERSION_SUPERSEDED,
    SourceUnavailable,
    read_evidence,
    read_version_evidence,
)
from services.parsing.graph import (
    REASON_CORRECTED_ENTITY_NOT_FOUND,
    REASON_CORRECTION_TARGET_NOT_ALLOWED,
    REASON_CORRECTION_WITHOUT_TARGET,
    REASON_INVALID_DECISION,
    REASON_RELATIONSHIP_NOT_FOUND,
    REASON_REVIEW_CONFLICT,
    ReviewRefused,
    read_relationships,
    record_review,
)

router = APIRouter(tags=["files"])


class FileListItem(BaseModel):
    file_id: str
    root_id: str
    version_id: str | None
    display_name: str
    relative_path: str
    presence_status: str
    status: str
    error_code: str | None
    updated_at: datetime


class EvidenceResponse(BaseModel):
    chunk_id: str
    file_id: str
    version_id: str
    relative_path: str
    page_number: int | None
    ordinal: int
    text: str
    content_sha256: str


class ReviewCreate(BaseModel):
    decision: str
    expected_revision: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=2000)
    actor: str | None = Field(default=None, max_length=100)
    corrected_entity_id: str | None = None


class ReviewResponse(BaseModel):
    relationship_id: str
    decision: str
    decision_revision: int


def _reason(code: str, message: str) -> dict[str, str]:
    return reason(code, message)


@router.get("/files", response_model=list[FileListItem])
def list_files(
    root_id: str = Query(min_length=1, max_length=36),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[FileListItem]:
    records = db.execute(
        select(FileRecord)
        .join(AuthorizedRoot, FileRecord.root_id == AuthorizedRoot.id)
        .where(
            FileRecord.root_id == root_id,
            AuthorizedRoot.status.in_(
                [RootStatus.ACTIVE.value, RootStatus.PAUSED.value]
            ),
        )
        .order_by(FileRecord.relative_path)
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    items: list[FileListItem] = []
    for file_record in records:
        version = (
            db.get(FileVersion, file_record.current_version_id)
            if file_record.current_version_id is not None
            else None
        )
        items.append(
            FileListItem(
                file_id=file_record.id,
                root_id=file_record.root_id,
                version_id=version.id if version is not None else None,
                display_name=file_record.name,
                relative_path=file_record.relative_path,
                presence_status=file_record.presence_status,
                status=version.status if version is not None else "discovered",
                error_code=version.error_code if version is not None else None,
                updated_at=file_record.updated_at,
            )
        )
    return items


@router.get("/evidence/{chunk_id}", response_model=EvidenceResponse)
def get_evidence(
    chunk_id: str,
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    try:
        evidence = read_evidence(db, chunk_id)
    except SourceUnavailable as exc:
        status_code = {
            REASON_CHUNK_NOT_FOUND: 404,
            REASON_FILE_MISSING: 404,
            REASON_ROOT_REVOKED: 403,
            REASON_VERSION_SUPERSEDED: 409,
            REASON_NO_CURRENT_VERSION: 503,
        }[exc.reason_code]
        raise HTTPException(
            status_code=status_code,
            detail=_reason(exc.reason_code, exc.message),
        ) from exc

    return EvidenceResponse(
        chunk_id=evidence.chunk_id,
        file_id=evidence.file_id,
        version_id=evidence.version_id,
        relative_path=evidence.relative_path,
        page_number=evidence.page_number,
        ordinal=evidence.ordinal,
        text=evidence.text,
        content_sha256=evidence.content_sha256,
    )


@router.get("/files/{file_id}/evidence")
def get_file_evidence(
    file_id: str,
    version_id: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Temporary compatibility shim for the D file inspector.

    Deprecated by the shared contract: evidence is read chunk-by-chunk through
    ``/evidence/{chunk_id}``. Remove this route once the front end calls that
    endpoint; do not add new fields to it.
    """
    file_record = db.get(FileRecord, file_id)
    version = db.get(FileVersion, version_id)
    if file_record is None or version is None or version.file_id != file_id:
        raise HTTPException(
            status_code=404,
            detail=_reason(REASON_FILE_MISSING, "No such file or version"),
        )
    if file_record.current_version_id != version_id:
        raise HTTPException(
            status_code=409,
            detail=_reason(REASON_VERSION_SUPERSEDED, "The requested version is not current"),
        )

    try:
        evidence_items = read_version_evidence(db, version_id)
    except SourceUnavailable as exc:
        status_code = {
            REASON_CHUNK_NOT_FOUND: 404,
            REASON_FILE_MISSING: 404,
            REASON_ROOT_REVOKED: 403,
            REASON_VERSION_SUPERSEDED: 409,
            REASON_NO_CURRENT_VERSION: 503,
        }[exc.reason_code]
        raise HTTPException(
            status_code=status_code,
            detail=_reason(exc.reason_code, exc.message),
        ) from exc

    if not evidence_items:
        raise HTTPException(
            status_code=422,
            detail=_reason("no_evidence", "This version has no stored passages"),
        )

    return [
        {
            "file_id": evidence.file_id,
            "version_id": evidence.version_id,
            "page": evidence.page_number,
            "source_path": evidence.relative_path,
            "excerpt": evidence.text,
            "evidence_id": evidence.chunk_id,
        }
        for evidence in evidence_items
    ]


@router.get("/versions/{version_id}/relations")
def get_relations(
    version_id: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    if db.get(FileVersion, version_id) is None:
        raise HTTPException(
            status_code=404,
            detail=_reason("version_not_found", "No such file version"),
        )

    return [
        {
            "relationship_id": view.relationship_id,
            "entity_type": view.entity_type,
            "label": view.label,
            "relation_type": view.relation_type,
            "kind": view.kind,
            "origin": view.origin,
            "producer_revision": view.producer_revision,
            "page_number": view.page_number,
            "quote": view.quote,
            "evidence_missing": view.evidence_missing,
            "decision": view.decision,
            "corrected_entity_id": view.corrected_entity_id,
            "decision_revision": view.decision_revision,
        }
        for view in read_relationships(db, version_id)
    ]


@router.post(
    "/relations/{relationship_id}/reviews",
    response_model=ReviewResponse,
)
def create_review(
    relationship_id: str,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
) -> ReviewResponse:
    try:
        revision = record_review(
            db,
            relationship_id,
            decision=payload.decision,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
            actor=payload.actor,
            corrected_entity_id=payload.corrected_entity_id,
        )
    except ReviewRefused as exc:
        status_code = {
            REASON_RELATIONSHIP_NOT_FOUND: 404,
            REASON_CORRECTED_ENTITY_NOT_FOUND: 404,
            REASON_REVIEW_CONFLICT: 409,
            REASON_INVALID_DECISION: 422,
            REASON_CORRECTION_WITHOUT_TARGET: 422,
            REASON_CORRECTION_TARGET_NOT_ALLOWED: 422,
        }[exc.reason_code]
        raise HTTPException(
            status_code=status_code,
            detail=_reason(exc.reason_code, exc.message),
        ) from exc

    return ReviewResponse(
        relationship_id=relationship_id,
        decision=payload.decision,
        decision_revision=revision,
    )
