"""Publish keyword fields with source text, independently of optional AI work."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import ChunkSearchIndex, SourceChunk


def prepare_keyword_indexes(db: Session, version_id: str) -> list[SourceChunk]:
    """Prepare derived fields without committing the caller's parse transaction."""
    chunks = list(db.scalars(
        select(SourceChunk)
        .where(SourceChunk.version_id == version_id)
        .order_by(SourceChunk.ordinal)
    ))
    for chunk in chunks:
        index = db.get(ChunkSearchIndex, chunk.id)
        if index is None:
            db.add(ChunkSearchIndex(chunk_id=chunk.id, search_text=chunk.text))
        else:
            index.search_text = chunk.text
    db.flush()
    return chunks
