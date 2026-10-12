from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.common.db import Base


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
    # A job now targets exactly one of: a case (the original starter flow),
    # an authorized root, or a file version. The starter's case flow is
    # unchanged - it keeps filling case_id.
    case_id: Mapped[str | None] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    root_id: Mapped[str | None] = mapped_column(
        ForeignKey("authorized_roots.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE"),
        nullable=True,
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


# ---------------------------------------------------------------------------
# W7 vertical slice: read-only index over a user-authorized folder.
#
# The originals are never copied, renamed, or modified. We only record where
# they are, which content version we indexed, and the text we extracted.
# ---------------------------------------------------------------------------


class RootStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKING = "revoking"
    REVOKED = "revoked"


class FilePresence(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


class VersionStatus(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTING = "extracting"
    BASIC_READY = "basic_ready"
    ENRICHED = "enriched"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class RootJobType(StrEnum):
    SCAN_ROOT = "scan_root"
    EXTRACT_FILE = "extract_file"


class AuthorizedRoot(Base):
    """A folder the user explicitly authorized for indexing."""

    __tablename__ = "authorized_roots"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    mount_id: Mapped[str] = mapped_column(String(100), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RootStatus.ACTIVE.value,
        index=True,
    )
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    __table_args__ = (
        UniqueConstraint("mount_id", "relative_path", name="uq_root_mount_path"),
    )


class FileRecord(Base):
    """A file's location on disk. We record it; we never move it."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    root_id: Mapped[str] = mapped_column(
        ForeignKey("authorized_roots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Points at the current version. Deliberately not a database-level foreign
    # key, to avoid a circular dependency with file_versions; the worker's
    # publication transaction is responsible for keeping it consistent.
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    presence_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=FilePresence.PRESENT.value,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    __table_args__ = (
        UniqueConstraint("root_id", "relative_path", name="uq_file_root_path"),
    )


class FileVersion(Base):
    """One immutable content version of a file.

    When the content changes we add a new version; the previous one is never
    overwritten, so old evidence and review decisions stay explainable.
    """

    __tablename__ = "file_versions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=VersionStatus.DISCOVERED.value,
        index=True,
    )
    parser_revision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("file_id", "content_sha256", name="uq_version_file_hash"),
    )


class SourceChunk(Base):
    """A located piece of extracted text, used to show source evidence."""

    __tablename__ = "source_chunks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_chunk_version_ordinal"),
    )
