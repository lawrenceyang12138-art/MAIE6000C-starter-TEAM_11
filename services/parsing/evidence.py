"""Read a stored passage back as evidence, refusing stale or missing sources.

This is what makes a search result trustworthy: the passage we hand back is
not just text we once extracted, it is text that is still the current content
of a file the user still authorises us to read.

Every refusal carries a reason code, because "no result" and "this result used
to be valid" are different things and the interface has to be able to say
which one happened.

Checked in this order, cheapest first:

1. the chunk exists
2. its file still points at this version as the current one
3. the authorised root has not been revoked
4. the authorized path still resolves inside its configured mount
5. the bytes on disk still have the version's SHA-256 and byte size

"The file has newer content" and "no version of this file has been marked
current yet" are different situations with different fixes, so they carry
different reason codes. Collapsing them would send whoever is debugging a
working extraction pipeline looking for a newer version that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
)
from services.parsing.pdf import SourceMissing, file_identity

REASON_CHUNK_NOT_FOUND = "chunk_not_found"
REASON_NO_CURRENT_VERSION = "no_current_version"
REASON_VERSION_SUPERSEDED = "version_superseded"
REASON_FILE_MISSING = "file_missing"
REASON_ROOT_REVOKED = "root_revoked"
REASON_PATH_OUT_OF_SCOPE = "path_out_of_scope"
REASON_SOURCE_CHANGED = "source_changed"


class SourceUnavailable(Exception):
    """The passage cannot be served, with a reason the caller can show."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


@dataclass(frozen=True)
class Evidence:
    """One located passage, with everything needed to cite it."""

    chunk_id: str
    version_id: str
    file_id: str
    relative_path: str
    page_number: int | None
    ordinal: int
    text: str
    content_sha256: str


def read_evidence(db: Session, chunk_id: str) -> Evidence:
    """Return one stored passage, or raise SourceUnavailable explaining why not.

    A version that is no longer current is treated as stale on purpose: the
    text may still be readable, but it no longer describes what is on disk, so
    presenting it as a current answer would be misleading.
    """
    chunk = db.get(SourceChunk, chunk_id)
    if chunk is None:
        raise SourceUnavailable(REASON_CHUNK_NOT_FOUND, "No such passage")

    version, file_record, _ = readable_version_source(db, chunk.version_id)

    return Evidence(
        chunk_id=chunk.id,
        version_id=version.id,
        file_id=file_record.id,
        relative_path=file_record.relative_path,
        page_number=chunk.page_number,
        ordinal=chunk.ordinal,
        text=chunk.text,
        content_sha256=version.content_sha256,
    )


def readable_version_source(
    db: Session, version_id: str
) -> tuple[FileVersion, FileRecord, Path]:
    """Verify the current authorized source behind one version."""
    version = db.get(FileVersion, version_id)
    if version is None:
        raise SourceUnavailable(
            REASON_VERSION_SUPERSEDED, "The version behind this passage is gone"
        )

    file_record = db.get(FileRecord, version.file_id)
    if file_record is None:
        raise SourceUnavailable(REASON_FILE_MISSING, "The file record is gone")

    if file_record.current_version_id is None:
        raise SourceUnavailable(
            REASON_NO_CURRENT_VERSION,
            "No version of this file has been marked current, so nothing from "
            "it can be served yet",
        )

    if file_record.current_version_id != version.id:
        raise SourceUnavailable(
            REASON_VERSION_SUPERSEDED,
            "The file has newer content; this passage is historical",
        )

    if file_record.presence_status != FilePresence.PRESENT.value:
        raise SourceUnavailable(
            REASON_FILE_MISSING,
            f"The file is no longer available ({file_record.presence_status})",
        )

    root = db.get(AuthorizedRoot, file_record.root_id)
    if root is None or root.status not in {
        RootStatus.ACTIVE.value,
        RootStatus.PAUSED.value,
    }:
        status = root.status if root is not None else "missing"
        raise SourceUnavailable(
            REASON_ROOT_REVOKED, f"The folder authorisation is not readable ({status})"
        )

    # Reuse A's mount allowlist and canonical containment checks. A local
    # import avoids a package-initialization cycle through ``services.scan``.
    from services.scan.handler import MountNotAllowed, PathEscapesRoot, resolve_source_path

    try:
        source_path = resolve_source_path(db, version.id, for_write=False)
    except (MountNotAllowed, PathEscapesRoot) as exc:
        raise SourceUnavailable(
            REASON_PATH_OUT_OF_SCOPE,
            "The authorized source path can no longer be resolved safely",
        ) from exc
    except LookupError as exc:
        raise SourceUnavailable(
            REASON_FILE_MISSING,
            "The source record behind this passage is unavailable",
        ) from exc

    try:
        actual_sha256, actual_size = file_identity(source_path)
    except SourceMissing as exc:
        raise SourceUnavailable(
            REASON_FILE_MISSING,
            "The source file is missing or unreadable",
        ) from exc

    if actual_sha256 != version.content_sha256 or actual_size != version.byte_size:
        raise SourceUnavailable(
            REASON_SOURCE_CHANGED,
            "The source file has changed since this version was indexed; rescan it",
        )

    return version, file_record, source_path


def read_version_evidence(db: Session, version_id: str) -> list[Evidence]:
    """Read every passage for one version after a single source check.

    This is the batch counterpart to ``read_evidence`` for the temporary
    file-level compatibility view. It preserves the same reason codes while
    avoiding one root/file/version check per chunk.
    """
    version, file_record, _ = readable_version_source(db, version_id)
    chunks = db.execute(
        select(SourceChunk)
        .where(SourceChunk.version_id == version.id)
        .order_by(SourceChunk.ordinal)
    ).scalars().all()
    return [
        Evidence(
            chunk_id=chunk.id,
            version_id=version.id,
            file_id=file_record.id,
            relative_path=file_record.relative_path,
            page_number=chunk.page_number,
            ordinal=chunk.ordinal,
            text=chunk.text,
            content_sha256=version.content_sha256,
        )
        for chunk in chunks
    ]
