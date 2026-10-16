from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    literal_column,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.common.db import Base
from services.search.text import DIMENSIONS, normalize_text, search_terms


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseStatus(StrEnum):
    NEW = "new"
    QUEUED = "queued"
    TRIAGED = "triaged"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    TRIAGE_CASE = "triage_case"


class SourceFileStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class SourceVersionStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CaseStatus.NEW.value,
        index=True,
    )
    ai_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    jobs: Mapped[list["Job"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=JobType.TRIAGE_CASE.value,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=JobStatus.PENDING.value,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    case: Mapped[Case] = relationship(back_populates="jobs")


class SourceFile(Base):
    """A scanned source file that can have multiple immutable versions."""

    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SourceFileStatus.READY.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    versions: Mapped[list["SourceVersion"]] = relationship(
        back_populates="source_file",
        cascade="all, delete-orphan",
        order_by="SourceVersion.version_number",
    )


class SourceVersion(Base):
    """An immutable parsed version of a source file."""

    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "version_number",
            name="uq_source_versions_file_version",
        ),
        CheckConstraint("version_number >= 1", name="ck_source_versions_number"),
        Index(
            "uq_source_versions_current_file",
            "source_file_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SourceVersionStatus.READY.value,
        index=True,
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    source_file: Mapped[SourceFile] = relationship(back_populates="versions")
    chunks: Mapped[list["SourceChunk"]] = relationship(
        back_populates="source_version",
        cascade="all, delete-orphan",
        order_by="SourceChunk.chunk_index",
    )


class SourceChunk(Base):
    """A searchable text chunk with its source page range and embedding."""

    __tablename__ = "source_chunks"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id",
            "chunk_index",
            name="uq_source_chunks_version_index",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_source_chunks_index"),
        CheckConstraint(
            "page_start >= 1 AND page_end >= page_start",
            name="ck_source_chunks_pages",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    source_version_id: Mapped[str] = mapped_column(
        ForeignKey("source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search_terms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(DIMENSIONS).with_variant(JSON(none_as_null=True), "sqlite"),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    source_version: Mapped[SourceVersion] = relationship(back_populates="chunks")


keyword_index = Index(
    "ix_source_chunks_keyword",
    func.to_tsvector(literal_column("'simple'"), SourceChunk.search_terms),
    postgresql_using="gin",
).ddl_if(dialect="postgresql")
SourceChunk.__table__.append_constraint(keyword_index)


@event.listens_for(SourceChunk, "before_insert")
@event.listens_for(SourceChunk, "before_update")
def prepare_search_text(mapper, connection, chunk: SourceChunk) -> None:
    chunk.search_text = normalize_text(chunk.text)
    chunk.search_terms = search_terms(chunk.text)
