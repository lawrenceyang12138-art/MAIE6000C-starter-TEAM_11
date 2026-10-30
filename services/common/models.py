from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
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
    # Stable, machine-readable reason the last attempt failed. ``error`` stays a
    # diagnostic string that never leaves the service; this column is what the
    # public ``error_code`` is read from, so a client can tell a transient
    # "file_missing" (retry once the file is back) from an internal failure.
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    EMBED_FILE = "embed_file"


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
    # Why the last scan could not read the file, when it could not. ``missing``
    # and ``unavailable`` say *that* the content is not usable; this says what
    # the scanner actually hit, in the same vocabulary extraction uses.
    presence_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
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


# Search data is derived from, and shares the identity of, a canonical chunk.
class ChunkSearchIndex(Base):
    __tablename__ = "chunk_search_index"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("source_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search_terms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(DIMENSIONS).with_variant(JSON(none_as_null=True), "sqlite"),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


keyword_index = Index(
    "ix_chunk_search_index_keyword",
    func.to_tsvector(literal_column("'simple'"), ChunkSearchIndex.search_terms),
    postgresql_using="gin",
).ddl_if(dialect="postgresql")
ChunkSearchIndex.__table__.append_constraint(keyword_index)


@event.listens_for(ChunkSearchIndex, "before_insert")
@event.listens_for(ChunkSearchIndex, "before_update")
def prepare_search_text(mapper, connection, index: ChunkSearchIndex) -> None:
    index.search_text = normalize_text(index.search_text or "")
    index.search_terms = search_terms(index.search_text)


# ---------------------------------------------------------------------------
# W7 minimal relations and review.
#
# Proposal from the read-files workstream for A to review: the schedule gives A
# ownership of the shared schema, so this is written to be adopted, changed, or
# rejected rather than treated as settled.
#
# Scope is deliberately small. A relation is only stored when the source text
# supports it, and every relation carries the passage that justifies it. This
# is a candidate for a human to confirm, not a claim of fact.
# ---------------------------------------------------------------------------


class EntityType(StrEnum):
    PERSON = "person"
    PROJECT = "project"
    TOPIC = "topic"


class RelationType(StrEnum):
    MENTIONS = "mentions"


class RelationKind(StrEnum):
    SOURCE_SUPPORTED = "source_supported"


class RelationOrigin(StrEnum):
    RULE = "rule"
    USER = "user"


class ReviewDecision(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class Entity(Base):
    """One candidate identity, e.g. a person or a project name.

    Names are not unique keys: two people can share a name, so the identity is
    the row, not the label.
    """

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    display_label: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "normalized_label", name="uq_entity_type_label"),
    )


class Relationship(Base):
    """A candidate link between a file version and an entity it mentions."""

    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    source_version_id: Mapped[str] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RelationType.MENTIONS.value
    )
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RelationKind.SOURCE_SUPPORTED.value
    )
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RelationOrigin.RULE.value
    )
    # What produced this candidate, so a rule can be told apart from a model
    # run and both can be revisited.
    producer_revision: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "source_version_id",
            "object_entity_id",
            "relation_type",
            name="uq_relationship_version_entity_type",
        ),
    )


class RelationshipEvidence(Base):
    """The passage that justifies a relationship.

    A relation without evidence is a claim the user cannot check, so storing
    the quote and its location is not optional.
    """

    __tablename__ = "relationship_evidence"

    relationship_id: Mapped[str] = mapped_column(
        ForeignKey("relationships.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("source_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    start_offset: Mapped[int] = mapped_column(Integer, primary_key=True)
    end_offset: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Review(Base):
    """A human decision about a relationship. Append-only, latest wins."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    relationship_id: Mapped[str] = mapped_column(
        ForeignKey("relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # When the decision is "corrected", what the reviewer says it should be.
    # Null for confirmations and rejections, which do not name a replacement.
    corrected_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "relationship_id", "decision_revision", name="uq_review_relationship_revision"
        ),
    )
