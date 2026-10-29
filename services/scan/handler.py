"""Scan handler: discover files under an authorized root and version them.

Owned by A (backend / filesystem). This is the read side of the filesystem
adapter described in week04 ``docs/architecture.md``:

- the scan *observes* content and records it (workflow step 4, "persists its
  location and content version");
- ``files.current_version_id`` is set here, in the same transaction, because the
  pointer means "latest observed content", not "latest parsed content" (D1);
- dispatch is idempotent: only versions that were never processed get an
  ``extract_file`` job, and unchanged content reuses the existing version row
  (D5). Re-observing known content still moves the pointer back when the file
  was reverted to an earlier revision, so the pointer always names the bytes
  currently on disk;
- a file the scan cannot read is *recorded*, not skipped: it keeps a row with
  ``presence_status`` of ``missing`` or ``unavailable`` and the reason the read
  failed, and that row is never left saying ``present`` afterwards. One bad
  file never stops the rest of the scan;
- the source tree is never written to; the mount is read-only (``:ro``).

Separation from B's modules: hashing and extraction are reused from
``services.parsing``; this module owns traversal, records, the pointer and
dispatch. The API keeps its own HTTP-level path normalisation; the copy here is
deliberately pure (raises ``ValueError``) so the worker can use it too.
"""

from __future__ import annotations

import os
import stat
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
from services.parsing.pdf import (
    REASON_FILE_MISSING,
    REASON_UNREADABLE,
    SourceMissing,
    file_identity,
)

# Reasons recorded on ``files.presence_reason``. The first two reuse the
# extraction vocabulary on purpose: "the file is gone" and "the file cannot be
# read" must mean the same thing whether the scan or the parser noticed it.
PRESENCE_REASON_FILE_MISSING = REASON_FILE_MISSING
PRESENCE_REASON_UNREADABLE = REASON_UNREADABLE
# A socket, FIFO or device inside the corpus has no bytes to version, and
# opening one can block the whole scan. It is recorded and skipped.
PRESENCE_REASON_NOT_REGULAR = "not_a_regular_file"


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


def resolve_source_path(db: Session, version_id: str, *, for_write: bool = True) -> Path:
    """Resolve the container path of a file version for extraction or preview.

    Every hop is containment-checked (mount, then authorized root, then file).
    A revoked root always refuses the read. ``for_write`` keeps the two callers
    apart: new work (extraction) requires an ``active`` root, while reads of
    already-indexed content (preview, evidence) must also work for a ``paused``
    root: pausing stops new jobs, it does not hide existing content (§8-B.4).
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
    allowed = (
        {RootStatus.ACTIVE.value}
        if for_write
        else {RootStatus.ACTIVE.value, RootStatus.PAUSED.value}
    )
    if root.status not in allowed:
        raise PathEscapesRoot(
            f"root {root.id} is {root.status}, not readable for this operation"
        )
    root_dir = _contained(resolve_mount_path(root.mount_id), root.relative_path)
    return _contained(root_dir, record.relative_path)


def _iter_source_files(root_dir: Path, unreadable_dirs: list[str] | None = None):
    """Yield regular files under root_dir, skipping hidden and symlinked entries.

    Discovery does not filter by extension (D4): whether a document can be
    parsed is decided by extraction, not by its filename, and unsupported
    entries must stay visible as records.

    A directory that cannot be listed is reported through ``unreadable_dirs``
    instead of raising: one unreadable subdirectory must not abort the scan of
    the rest, and the caller can still say that it was not covered.
    """

    def _on_error(exc: OSError) -> None:
        if unreadable_dirs is not None:
            unreadable_dirs.append(getattr(exc, "filename", None) or "<unknown>")

    for dirpath, dirnames, filenames in os.walk(
        root_dir, followlinks=False, onerror=_on_error
    ):
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


def _is_regular_file(path: Path) -> bool:
    """Whether the entry has bytes we can version.

    Sockets, FIFOs and devices have no content to hash, and opening one can
    block the whole scan, so they are not read. A path that cannot be stated at
    all (it vanished between the walk and this call) reports ``True`` on
    purpose: the read that follows fails with an accurate reason instead of the
    scan inventing one here.
    """
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except OSError:
        return True


def _find_record(db: Session, root_id: str, relative_path: str) -> FileRecord | None:
    return db.execute(
        select(FileRecord).where(
            FileRecord.root_id == root_id,
            FileRecord.relative_path == relative_path,
        )
    ).scalars().first()


def _record_unreadable(
    db: Session,
    *,
    root_id: str,
    relative_path: str,
    name: str,
    reason: str,
) -> tuple[FileRecord, bool]:
    """Record a file the scan could not read; return ``(record, created)``.

    Two failures are kept apart because they mean different things to the user:
    ``missing`` is "it is not there any more" and ``unavailable`` is "it is
    there but we could not read it". Both keep the reason code, and neither
    leaves an existing row saying ``present`` - a file we failed to read is not
    evidence that its content is still indexed.

    ``last_seen_at`` deliberately keeps its old value: it records the last scan
    that actually read the bytes, which is more useful than the last time the
    name was noticed.
    """
    presence = (
        FilePresence.MISSING
        if reason == PRESENCE_REASON_FILE_MISSING
        else FilePresence.UNAVAILABLE
    )
    record = _find_record(db, root_id, relative_path)
    created = record is None
    if record is None:
        record = FileRecord(
            id=str(uuid4()),
            root_id=root_id,
            relative_path=relative_path,
            name=name,
            presence_status=presence.value,
            presence_reason=reason,
            last_seen_at=None,
        )
        db.add(record)
        db.flush()
    else:
        record.presence_status = presence.value
        record.presence_reason = reason
    return record, created


def _note_unreadable(
    db: Session,
    summary: dict,
    recorded: set[str],
    *,
    root_id: str,
    relative_path: str,
    name: str,
    reason: str,
) -> None:
    """Record one unreadable file, count it, and remember it for this scan."""
    record, created = _record_unreadable(
        db, root_id=root_id, relative_path=relative_path, name=name, reason=reason
    )
    recorded.add(relative_path)
    if created:
        summary["files_created"] += 1
    if record.presence_status == FilePresence.MISSING.value:
        summary["files_missing"] += 1
    else:
        summary["files_unavailable"] += 1


def handle_scan_root(db: Session, root_id: str, job_id: int | None = None) -> dict:
    """Scan one authorized root: observe, version, point, dispatch.

    The whole run is one transaction: observation, the current-version pointer
    and extraction dispatch land together or not at all (the publication
    transaction the spec requires). Returns a summary dict for logging.

    Files that cannot be read do not abort the run. They are recorded with a
    ``presence_status`` and reason, so the file list explains itself instead of
    the file quietly disappearing from it.
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
        "pointers_restored": 0,
        "files_missing": 0,
        "files_unavailable": 0,
        "directories_unreadable": 0,
        "unreadable_directories": [],
    }
    seen_paths: set[str] = set()
    recorded: set[str] = set()
    unreadable_dirs: list[str] = []

    for path in _iter_source_files(root_dir, unreadable_dirs):
        relative_path = path.relative_to(root_dir).as_posix()
        summary["files_seen"] += 1

        if not _is_regular_file(path):
            _note_unreadable(
                db,
                summary,
                recorded,
                root_id=root_id,
                relative_path=relative_path,
                name=path.name,
                reason=PRESENCE_REASON_NOT_REGULAR,
            )
            continue

        try:
            sha256, byte_size = file_identity(path)
        except SourceMissing as exc:
            # Gone between the walk and the read, or unreadable. Either way the
            # file is recorded with its reason instead of being skipped: a new
            # path deserves a row that says why it has no content, and an
            # existing row must stop claiming its content is present.
            _note_unreadable(
                db,
                summary,
                recorded,
                root_id=root_id,
                relative_path=relative_path,
                name=path.name,
                reason=exc.reason_code,
            )
            continue
        except OSError:
            # An I/O error is not a property of this document either. It is the
            # same class as "unreadable" and must not stop the other files.
            _note_unreadable(
                db,
                summary,
                recorded,
                root_id=root_id,
                relative_path=relative_path,
                name=path.name,
                reason=PRESENCE_REASON_UNREADABLE,
            )
            continue

        seen_paths.add(relative_path)
        record = _find_record(db, root_id, relative_path)
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
            record.presence_reason = None
            record.last_seen_at = utcnow()

        known_version = db.execute(
            select(FileVersion).where(
                FileVersion.file_id == record.id,
                FileVersion.content_sha256 == sha256,
            )
        ).scalars().first()
        if known_version is not None:
            # Content we have observed before. The pointer must still track it:
            # after a revert to an earlier revision it can legitimately point
            # elsewhere, and leaving it there would serve text that no longer
            # matches the disk (D1). Moving it back is not new work, so no
            # version is created and no new job is needed when the version was
            # already processed.
            if record.current_version_id != known_version.id:
                record.current_version_id = known_version.id
                summary["pointers_restored"] += 1
            # Re-dispatch only versions that were never processed, and only
            # while no live job for them exists. A ``failed`` or
            # ``unsupported`` version stays on the retry path instead of being
            # re-queued by every scan (§3.4.6 idempotency).
            if known_version.status == VersionStatus.DISCOVERED.value:
                live = db.execute(
                    select(Job)
                    .where(
                        Job.version_id == known_version.id,
                        Job.job_type == RootJobType.EXTRACT_FILE.value,
                        Job.status.in_(
                            [JobStatus.PENDING.value, JobStatus.CLAIMED.value]
                        ),
                    )
                    .limit(1)
                ).scalars().first()
                if live is None:
                    db.add(
                        Job(
                            root_id=root_id,
                            version_id=known_version.id,
                            job_type=RootJobType.EXTRACT_FILE.value,
                            status=JobStatus.PENDING.value,
                        )
                    )
                    summary["jobs_dispatched"] += 1
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

    # Everything this scan did not account for is gone. The check is on the
    # in-memory state, not on a fresh query: the session does not autoflush, so
    # a row this scan already marked ``unavailable`` would still look
    # ``present`` in the database and be overwritten with the wrong reason.
    #
    # ``unavailable`` from an earlier scan is promoted here too: if the path is
    # not there at all any more, "we could not read it" is no longer the truth,
    # and a stale reason would send the user looking for a permission problem
    # on a file that no longer exists.
    records = db.execute(select(FileRecord).where(FileRecord.root_id == root_id)).scalars()
    for record in records:
        if record.relative_path in seen_paths or record.relative_path in recorded:
            continue
        if record.presence_status == FilePresence.MISSING.value:
            continue
        record.presence_status = FilePresence.MISSING.value
        record.presence_reason = PRESENCE_REASON_FILE_MISSING
        # The pointer deliberately stays on the last observed version: the
        # content we indexed is still the last content this path had, and
        # evidence reads answer ``file_missing`` because of the presence
        # status rather than because the history was thrown away.
        summary["files_missing"] += 1

    # Not a per-file outcome (a directory is not a file record), but it must
    # still be visible: files under an unlistable directory were not covered by
    # this scan, and silence there would read as "all files are gone".
    summary["directories_unreadable"] = len(unreadable_dirs)
    summary["unreadable_directories"] = sorted(unreadable_dirs)

    root.last_successful_scan_at = utcnow()
    db.commit()
    return summary
