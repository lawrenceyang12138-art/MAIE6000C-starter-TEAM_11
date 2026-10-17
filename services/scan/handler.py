"""Discover files below an explicitly authorized root.

The scan transaction owns the current-version pointer and the first extraction
job for each new content version. Original files are opened read-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    VersionStatus,
    utcnow,
)
from services.parsing.pdf import SourceMissing, file_identity


class ScanPathError(ValueError):
    """A mount, root or file does not resolve inside its authorized boundary."""


@dataclass(frozen=True)
class ScanSummary:
    files_seen: int
    files_created: int
    files_missing: int
    versions_created: int
    jobs_created: int


def _mount_base(mount_id: str, source_mounts: dict[str, str]) -> Path:
    configured = source_mounts.get(mount_id)
    if configured is None:
        raise ScanPathError(f"Unknown mount_id {mount_id!r}")
    base = Path(configured).resolve()
    if not base.is_dir():
        raise ScanPathError(f"Configured mount is unavailable: {mount_id!r}")
    return base


def resolve_authorized_root(
    mount_id: str,
    root_relative_path: str,
    source_mounts: dict[str, str],
) -> Path:
    """Resolve an authorized root and reject absolute/parent/symlink escapes."""
    base = _mount_base(mount_id, source_mounts)
    relative = Path(root_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ScanPathError("Authorized root must be a relative path without '..'")

    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base) or not resolved.is_dir():
        raise ScanPathError("Authorized root escapes or is unavailable")
    return resolved


def resolve_file_path(
    mount_id: str,
    root_relative_path: str,
    file_relative_path: str,
    source_mounts: dict[str, str],
) -> Path:
    """Resolve one file and require it to remain inside its authorized root."""
    auth_root = resolve_authorized_root(mount_id, root_relative_path, source_mounts)
    relative = Path(file_relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ScanPathError("File path must be relative without '..'")

    resolved = (auth_root / relative).resolve()
    if not resolved.is_relative_to(auth_root) or not resolved.is_file():
        raise ScanPathError("File escapes or is unavailable")
    return resolved


def _iter_files(root_path: Path):
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and not (current / name).is_symlink()
        ]
        for name in filenames:
            candidate = current / name
            if name.startswith(".") or candidate.is_symlink():
                continue
            yield candidate


def _active_extract_job(db: Session, version_id: str) -> Job | None:
    return (
        db.execute(
            select(Job)
            .where(
                Job.version_id == version_id,
                Job.job_type == RootJobType.EXTRACT_FILE.value,
                Job.status.in_(
                    [
                        JobStatus.PENDING.value,
                        JobStatus.CLAIMED.value,
                        JobStatus.RETRY_WAIT.value,
                    ]
                ),
            )
            .limit(1)
        )
        .scalars()
        .first()
    )


def scan_root(
    db: Session,
    root: AuthorizedRoot,
    source_mounts: dict[str, str],
) -> ScanSummary:
    """Reconcile one authorized root into files, versions and extraction jobs."""
    root_path = resolve_authorized_root(
        root.mount_id,
        root.relative_path,
        source_mounts,
    )

    existing_files = {
        file_record.relative_path: file_record
        for file_record in db.execute(
            select(FileRecord).where(FileRecord.root_id == root.id)
        )
        .scalars()
        .all()
    }
    seen: set[str] = set()
    files_created = 0
    versions_created = 0
    jobs_created = 0

    try:
        for path in _iter_files(root_path):
            relative_path = path.relative_to(root_path).as_posix()
            seen.add(relative_path)
            try:
                content_sha256, byte_size = file_identity(path)
            except (OSError, SourceMissing):
                # An unreadable entry is skipped without stopping other files.
                continue

            file_record = existing_files.get(relative_path)
            if file_record is None:
                file_record = FileRecord(
                    root_id=root.id,
                    relative_path=relative_path,
                    name=path.name,
                    presence_status=FilePresence.PRESENT.value,
                )
                db.add(file_record)
                db.flush()
                existing_files[relative_path] = file_record
                files_created += 1

            file_record.presence_status = FilePresence.PRESENT.value
            file_record.last_seen_at = utcnow()

            current = (
                db.get(FileVersion, file_record.current_version_id)
                if file_record.current_version_id is not None
                else None
            )
            if current is not None and current.content_sha256 == content_sha256:
                continue

            version = (
                db.execute(
                    select(FileVersion).where(
                        FileVersion.file_id == file_record.id,
                        FileVersion.content_sha256 == content_sha256,
                    )
                )
                .scalars()
                .first()
            )
            created_version = version is None
            if version is None:
                version = FileVersion(
                    file_id=file_record.id,
                    content_sha256=content_sha256,
                    byte_size=byte_size,
                    status=VersionStatus.DISCOVERED.value,
                )
                db.add(version)
                db.flush()
                versions_created += 1

            file_record.current_version_id = version.id

            should_extract = version.status in {
                VersionStatus.DISCOVERED.value,
                VersionStatus.FAILED.value,
            }
            if created_version or should_extract:
                if _active_extract_job(db, version.id) is None:
                    db.add(
                        Job(
                            version_id=version.id,
                            job_type=RootJobType.EXTRACT_FILE.value,
                            status=JobStatus.PENDING.value,
                        )
                    )
                    jobs_created += 1

        missing = 0
        for relative_path, file_record in existing_files.items():
            if relative_path not in seen:
                if file_record.presence_status != FilePresence.MISSING.value:
                    missing += 1
                file_record.presence_status = FilePresence.MISSING.value

        root.last_successful_scan_at = utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ScanSummary(
        files_seen=len(seen),
        files_created=files_created,
        files_missing=missing,
        versions_created=versions_created,
        jobs_created=jobs_created,
    )
