"""C-owned token-vector sidecar; canonical source identities remain unchanged.

The explicit preparation function is for isolated C validation. A owns the
integrated Alembic migration; reads never create or alter database tables.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.common.db import Base
from services.common.models import SourceChunk  # noqa: F401 - register FK target
from services.search.text import MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChunkTokenIndex(Base):
    """One ragged token matrix for a source chunk under the selected model."""

    __tablename__ = "chunk_token_search_index"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("source_chunks.id", ondelete="CASCADE"), primary_key=True,
    )
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    token_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_vectors: Mapped[list[list[float]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False,
    )
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )


def text_fingerprint(text: str) -> str:
    """Identity of full stored text, including portions beyond model truncation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compatible_index_predicate():
    return (
        (ChunkTokenIndex.model_id == MODEL_ID)
        & (ChunkTokenIndex.model_revision == MODEL_REVISION)
        & (ChunkTokenIndex.token_dimensions == TOKEN_DIMENSIONS)
        & (ChunkTokenIndex.token_count > 0)
    )


def index_matches_text(index: ChunkTokenIndex | None, text: str) -> bool:
    """Reject stale content, different models and malformed stored matrices."""
    if index is None or (
        index.model_id != MODEL_ID
        or index.model_revision != MODEL_REVISION
        or index.token_dimensions != TOKEN_DIMENSIONS
        or type(index.token_count) is not int
        or index.token_count < 1
        or index.text_sha256 != text_fingerprint(text)
        or not isinstance(index.token_vectors, list)
        or len(index.token_vectors) != index.token_count
    ):
        return False
    from services.search.embeddings import EmbeddingUnavailable, validate_vectors

    try:
        validate_vectors([index.token_vectors], 1)
    except (EmbeddingUnavailable, TypeError, ValueError, OverflowError):
        return False
    return True


def token_index_available(db: Session) -> bool:
    """Read catalog state before querying, avoiding failed PostgreSQL transactions."""
    connection = db.connection()
    schema_map = connection.get_execution_options().get("schema_translate_map", {})
    schema = schema_map.get(None)
    return inspect(connection).has_table(ChunkTokenIndex.__tablename__, schema=schema)


def prepare_search_schema(engine) -> None:
    """Explicitly prepare C's additive sidecars, preserving all shared tables."""
    from services.search.page_metadata import VersionPageMetadata

    ChunkTokenIndex.__table__.create(bind=engine, checkfirst=True)
    VersionPageMetadata.__table__.create(bind=engine, checkfirst=True)
