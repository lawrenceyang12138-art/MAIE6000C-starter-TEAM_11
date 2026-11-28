"""Verified physical PDF page counts, derived from canonical source versions.

Only explicit indexing/preparation reads files or writes this C-owned sidecar.
Search reads identity-bound metadata without opening PDFs or creating tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.common.db import Base
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    VersionStatus,
)
from services.parsing.pdf import SourceMissing, file_identity
from services.scan.handler import MountNotAllowed, PathEscapesRoot, resolve_source_path

PAGE_METADATA_POLICY = "pdf-physical-pages-v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VersionPageMetadata(Base):
    """Actual PDF page count, including blank pages, for one immutable version."""

    __tablename__ = "version_page_search_metadata"

    version_id: Mapped[str] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE"), primary_key=True,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_revision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_revision: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )

    __table_args__ = (
        CheckConstraint("page_count > 0", name="ck_version_page_count_positive"),
        CheckConstraint("byte_size >= 0", name="ck_version_page_byte_size_nonnegative"),
    )


@dataclass(frozen=True)
class PageMetadataResult:
    version_id: str
    page_count: int | None = None
    error: str | None = None


def page_metadata_available(db: Session) -> bool:
    """Check catalog state without issuing a failing select or implicit DDL."""
    connection = db.connection()
    schema_map = connection.get_execution_options().get("schema_translate_map", {})
    return inspect(connection).has_table(
        VersionPageMetadata.__tablename__, schema=schema_map.get(None),
    )


def metadata_matches_version(metadata: VersionPageMetadata | None, version: FileVersion) -> bool:
    return metadata is not None and (
        metadata.version_id == version.id
        and metadata.content_sha256 == version.content_sha256
        and metadata.byte_size == version.byte_size
        and metadata.parser_revision == version.parser_revision
        and metadata.policy_revision == PAGE_METADATA_POLICY
        and type(metadata.page_count) is int
        and metadata.page_count > 0
    )


def load_page_metadata(db: Session, version: FileVersion) -> tuple[int | None, str]:
    """Read compatible metadata only; callers must first establish source scope."""
    if not page_metadata_available(db):
        return None, "page_metadata_schema_missing"
    metadata = db.get(VersionPageMetadata, version.id)
    if metadata is None:
        return None, "page_metadata_missing"
    if not metadata_matches_version(metadata, version):
        return None, "page_metadata_stale"
    return metadata.page_count, "ready"


def _read_physical_page_count(path: Path) -> tuple[int | None, str | None]:
    """Keep reader-specific failures separate from database exceptions."""
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                return None, "page_metadata_unsupported_format"
            stream.seek(0)
            reader = PdfReader(stream)
            if reader.is_encrypted:
                return None, "page_metadata_encrypted"
            count = len(reader.pages)
    except FileNotDecryptedError:
        return None, "page_metadata_encrypted"
    except PdfReadError:
        return None, "page_metadata_corrupt"
    except OSError:
        return None, "page_metadata_source_unavailable"
    except Exception:  # noqa: BLE001 - pypdf may surface malformed object errors
        return None, "page_metadata_corrupt"
    if type(count) is not int or count < 1:
        return None, "page_metadata_corrupt"
    return count, None


def prepare_version_page_metadata(db: Session, version_id: str) -> PageMetadataResult:
    """Verify current authorized bytes and publish their physical page count.

    This function never commits, creates tables, or changes source identities.
    The caller owns the transaction. SQL failures deliberately remain errors.
    """
    version = db.get(FileVersion, version_id)
    if version is None:
        return PageMetadataResult(version_id, error="page_metadata_version_missing")
    record = db.get(FileRecord, version.file_id)
    if record is None or record.presence_status != FilePresence.PRESENT.value:
        return PageMetadataResult(version_id, error="page_metadata_file_missing")
    if record.current_version_id != version.id:
        return PageMetadataResult(version_id, error="page_metadata_version_superseded")
    root = db.get(AuthorizedRoot, record.root_id)
    if root is None or root.status not in {RootStatus.ACTIVE.value, RootStatus.PAUSED.value}:
        return PageMetadataResult(version_id, error="page_metadata_root_not_authorized")
    if version.status not in {VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value}:
        return PageMetadataResult(version_id, error="page_metadata_version_not_ready")
    if not page_metadata_available(db):
        return PageMetadataResult(version_id, error="page_metadata_schema_missing")
    try:
        path = resolve_source_path(db, version.id, for_write=False)
    except MountNotAllowed:
        return PageMetadataResult(version_id, error="page_metadata_mount_unavailable")
    except (PathEscapesRoot, LookupError, OSError):
        return PageMetadataResult(version_id, error="page_metadata_path_unavailable")
    expected = (version.content_sha256, version.byte_size)
    try:
        before = file_identity(path)
        if before != expected:
            return PageMetadataResult(version_id, error="page_metadata_source_changed")
        page_count, error = _read_physical_page_count(path)
        after = file_identity(path)
    except (SourceMissing, OSError):
        return PageMetadataResult(version_id, error="page_metadata_source_unavailable")
    if before != after or after != expected:
        return PageMetadataResult(version_id, error="page_metadata_source_changed")
    if error is not None:
        return PageMetadataResult(version_id, error=error)
    metadata = db.get(VersionPageMetadata, version.id)
    if metadata is None:
        metadata = VersionPageMetadata(version_id=version.id)
        db.add(metadata)
    metadata.content_sha256, metadata.byte_size = expected
    metadata.parser_revision = version.parser_revision
    metadata.page_count = page_count
    metadata.policy_revision = PAGE_METADATA_POLICY
    db.flush()
    return PageMetadataResult(version_id, page_count=page_count)
