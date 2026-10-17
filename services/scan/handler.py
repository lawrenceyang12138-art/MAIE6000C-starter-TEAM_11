"""Scan handler: discover files under an authorized root and version them.

Owned by A (backend / filesystem). This is the read side of the filesystem
adapter described in week04 ``docs/architecture.md``:

- the scan *observes* content and records it (workflow step 4, "persists its
  location and content version");
- ``files.current_version_id`` is set here, in the same transaction, because the
  pointer means "latest observed content", not "latest parsed content" (D1);
- dispatch is idempotent: only newly created versions get an ``extract_file``
  job, and unchanged content reuses the existing version row (D5);
- the source tree is never written to; the mount is read-only (``:ro``).

Separation from B's modules: hashing and extraction are reused from
``services.parsing``; this module owns traversal, records, the pointer and
dispatch. The API keeps its own HTTP-level path normalisation; the copy here is
deliberately pure (raises ``ValueError``) so the worker can use it too.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
    VersionStatus,
    utcnow,
)
from services.parsing.pdf import SourceMissing, file_identity


class MountNotAllowed(ValueError):
    """mount_id is not in the server-side allowlist."""


class PathEscapesRoot(ValueError):
    """The resolved path is not contained by the mount and the authorized root."""


def _normalise_relative_path(relative_path: str) -> str:
    """Reject absolute paths and '..' segments; return a clean relative path.

    Mirrors the API-level normaliser, but raises ValueError instead of
    HTTPException so the worker can use the same rules.
    """
    cleaned = relative_path.strip().replace("\\", "/")
    if cleaned.startswith("/") or (len(cleaned) > 1 and cleaned[1] == ":"):
        raise PathEscapesRoot("Path must be relative to the configured mount")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathEscapesRoot("Path escapes the allowed mount")
    return "/".join(parts) or "."


def _contained(base: Path, relative_path: str) -> Path:
    """Resolve relative_path under base and require containment.

    ``resolve()`` collapses symlinks, so a link pointing outside the base is
    rejected here: a read-only mount alone is not sufficient authorization.
    """
    rel = _normalise_relative_path(relative_path)
    candidate = base.resolve() if rel == "." else (base / rel).resolve()
    base_real = base.resolve()
    if candidate != base_real and base_real not in candidate.parents:
        raise PathEscapesRoot(f"{relative_path!r} escapes {base_real}")
    return candidate


def resolve_mount_path(mount_id: str) -> Path:
    """Map a mount_id to its container path through the server-side allowlist."""
    mounts = get_settings().source_mounts
    if mount_id not in mounts:
        raise MountNotAllowed(f"Unknown mount_id: {mount_id!r}")
    return Path(mounts[mount_id])


def resolve_source_path(db: Session, version_id: str) -> Path:
    """Resolve the container path of a file version for extraction or preview.

    Every hop is containment-checked (mount, then authorized root, then file),
    and a revoked root refuses the read.
    """
    version = db.get(FileVersion, version_id)
    if version is None:
        raise LookupError(f"unknown file version {version_id}")
    record = db.get(FileRecord, version.file_id)
    if record is None:
        raise LookupError(f"unknown file record for version {version_id}")
    root = db.get(AuthorizedRoot, record.root_id)
    if root is None:
        raise LookupError(f"unknown root for file {record.id}")
    if root.status != RootStatus.ACTIVE.value:
        raise PathEscapesRoot(f"root {root.id} is {root.status}, not active")
    root_dir = _contained(resolve_mount_path(root.mount_id), root.relative_path)
    return _contained(root_dir, record.relative_path)


def _iter_source_files(root_dir: Path):
    """Yield regular files under root_dir, skipping hidden and symlinked entries.

    Discovery does not filter by extension (D4): whether a document can be
    parsed is decided by extraction, not by its filename, and unsupported
    entries must stay visible as records.
    """
    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and not (Path(dirpath) / name).is_symlink()
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            path = Path(dirpath) / filename
            if path.is_symlink():
                continue
            yield path


def handle_scan_root(db: Session, root_id: str, job_id: int | None = None) -> dict:
    """Scan one authorized root: observe, version, point, dispatch.

    The whole run is one transaction: observation, the current-version pointer
    and extraction dispatch land together or not at all (the publication
    transaction the spec requires). Returns a summary dict for logging.
    """
    root = db.get(AuthorizedRoot, root_id)
    if root is None:
        raise LookupError(f"unknown root {root_id}")
    if root.status != RootStatus.ACTIVE.value:
        raise ValueError(f"root {root_id} is {root.status}, not active")

    if job_id is not None:
        active = db.execute(
            select(Job)
            .where(
                Job.root_id == root_id,
                Job.job_type == RootJobType.SCAN_ROOT.value,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
                Job.id != job_id,
            )
            .limit(1)
        ).scalars().first()
        if active is not None:
            return {
                "outcome": "skipped",
                "reason": "another scan for this root is already active",
                "root_id": root_id,
            }

    root_dir = _contained(resolve_mount_path(root.mount_id), root.relative_path)
    if not root_dir.is_dir():
        raise ValueError(f"mount directory not found: {root_dir}")

    summary = {
        "outcome": "scanned",
        "root_id": root_id,
        "files_seen": 0,
        "files_created": 0,
        "versions_created": 0,
        "jobs_dispatched": 0,
        "files_missing": 0,
    }
    seen_paths: set[str] = set()

    for path in _iter_source_files(root_dir):
        relative_path = path.relative_to(root_dir).as_posix()
        seen_paths.add(relative_path)
        summary["files_seen"] += 1

        try:
            sha256, byte_size = file_identity(path)
        except SourceMissing:
            # Vanished between the walk and the read; the missing-file pass
            # below records it against any existing row.
            continue

        record = db.execute(
            select(FileRecord).where(
                FileRecord.root_id == root_id,
                FileRecord.relative_path == relative_path,
            )
        ).scalars().first()
        if record is None:
            record = FileRecord(
                id=str(uuid4()),
                root_id=root_id,
                relative_path=relative_path,
                name=path.name,
                presence_status=FilePresence.PRESENT.value,
                last_seen_at=utcnow(),
            )
            db.add(record)
            db.flush()
            summary["files_created"] += 1
        else:
            record.presence_status = FilePresence.PRESENT.value
            record.last_seen_at = utcnow()

        known_version = db.execute(
            select(FileVersion).where(
                FileVersion.file_id == record.id,
                FileVersion.content_sha256 == sha256,
            )
        ).scalars().first()
        if known_version is not None:
            # Unchanged content: reuse the version row, create nothing, and
            # leave the pointer where it is.
            continue

        version = FileVersion(
            id=str(uuid4()),
            file_id=record.id,
            content_sha256=sha256,
            byte_size=byte_size,
            status=VersionStatus.DISCOVERED.value,
        )
        db.add(version)
        db.flush()
        # D1: the scan sets the pointer, in the same transaction.
        record.current_version_id = version.id
        db.add(
            Job(
                root_id=root_id,
                version_id=version.id,
                job_type=RootJobType.EXTRACT_FILE.value,
                status=JobStatus.PENDING.value,
            )
        )
        summary["versions_created"] += 1
        summary["jobs_dispatched"] += 1

    present = db.execute(
        select(FileRecord).where(
            FileRecord.root_id == root_id,
            FileRecord.presence_status == FilePresence.PRESENT.value,
        )
    ).scalars()
    for record in present:
        if record.relative_path not in seen_paths:
            record.presence_status = FilePresence.MISSING.value
            # The pointer deliberately stays on the last observed version.
            summary["files_missing"] += 1

    root.last_successful_scan_at = utcnow()
    db.commit()
    return summary
