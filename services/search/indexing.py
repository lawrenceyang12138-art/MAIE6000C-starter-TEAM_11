from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import ChunkSearchIndex, SourceChunk
from services.search.embeddings import EmbeddingBackend, EmbeddingUnavailable, validate_vectors
from services.search.text import (
    DIMENSIONS,
    MAX_BATCH_SIZE,
    MAX_TEXT_CHARS,
    MODEL_ID,
    normalize_text,
    search_terms,
)


@dataclass(frozen=True)
class IndexResult:
    version_id: str
    chunk_count: int
    embedded_count: int
    embedding_error: str | None = None


def sync_chunk_index(db: Session, version_id: str) -> int:
    """Create or refresh derived keyword fields for one version's chunks.

    This function only writes to ``chunk_search_index``. The chunk text in
    ``source_chunks`` remains the canonical copy and is never rewritten here.
    """
    chunks = list(
        db.execute(
            select(SourceChunk)
            .where(SourceChunk.version_id == version_id)
            .order_by(SourceChunk.ordinal)
        )
        .scalars()
        .all()
    )
    chunk_ids = {chunk.id for chunk in chunks}
    existing = {
        row.chunk_id: row
        for row in db.execute(
            select(ChunkSearchIndex).where(ChunkSearchIndex.chunk_id.in_(chunk_ids))
        )
        .scalars()
        .all()
    } if chunk_ids else {}

    for chunk in chunks:
        normalized = normalize_text(chunk.text)
        terms = search_terms(chunk.text)
        row = existing.get(chunk.id)
        if row is None:
            db.add(
                ChunkSearchIndex(
                    chunk_id=chunk.id,
                    search_text=normalized,
                    search_terms=terms,
                )
            )
            continue
        if row.search_text != normalized or row.search_terms != terms:
            row.search_text = normalized
            row.search_terms = terms
            # A changed passage must not keep a vector produced from old text.
            row.embedding = None
            row.embedding_model = None
            row.embedding_dimensions = None

    for chunk_id, row in existing.items():
        if chunk_id not in chunk_ids:
            db.delete(row)

    db.flush()
    return len(chunks)


def embed_version(
    db: Session,
    version_id: str,
    backend: EmbeddingBackend,
) -> IndexResult:
    """Populate optional vectors in bounded batches.

    Text indexing is already complete. An unavailable or invalid embedding
    backend leaves the keyword index intact and returns a reason code; it does
    not turn a readable document into a failed parse.
    """
    sync_chunk_index(db, version_id)
    chunks = list(
        db.execute(
            select(SourceChunk)
            .where(SourceChunk.version_id == version_id)
            .order_by(SourceChunk.ordinal)
        )
        .scalars()
        .all()
    )
    if not chunks:
        return IndexResult(version_id, 0, 0, "no_chunks")
    if backend.model_id != MODEL_ID or backend.dimensions != DIMENSIONS:
        return IndexResult(version_id, len(chunks), 0, "embedding_model_mismatch")

    vectors: list[list[float]] = []
    try:
        for offset in range(0, len(chunks), MAX_BATCH_SIZE):
            batch = chunks[offset : offset + MAX_BATCH_SIZE]
            texts = [
                chunk.text[:MAX_TEXT_CHARS]
                for chunk in batch
            ]
            vectors.extend(validate_vectors(backend.embed(texts, "passage"), len(texts)))
    except EmbeddingUnavailable as exc:
        return IndexResult(version_id, len(chunks), 0, str(exc))

    index_by_chunk = {
        row.chunk_id: row
        for row in db.execute(
            select(ChunkSearchIndex).where(
                ChunkSearchIndex.chunk_id.in_([chunk.id for chunk in chunks])
            )
        )
        .scalars()
        .all()
    }
    for chunk, vector in zip(chunks, vectors, strict=True):
        row = index_by_chunk[chunk.id]
        row.embedding = vector
        row.embedding_model = MODEL_ID
        row.embedding_dimensions = DIMENSIONS
    db.flush()
    return IndexResult(version_id, len(chunks), len(vectors))
