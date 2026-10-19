"""Tests for the scan handler's observation and versioning rules.

The scan is the write side of the read-files pipeline: it observes what is
on disk, records versions for new content, moves the current-version
pointer, and dispatches extraction - all in one transaction. These tests
cover the rules that make repeated scans safe: idempotency, the pointer
semantics for changed and missing files, and containment of the root inside
its mount. The mount is served from a temporary directory through a patched
allowlist, so the filesystem is real.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootStatus,
)
from services.parsing.pdf import REASON_FILE_MISSING, SourceMissing
from services.scan import handler as scan_handler
from services.scan.handler import PathEscapesRoot, handle_scan_root


class _Settings:
    def __init__(self, source_mounts: dict[str, str]) -> None:
        self.source_mounts = source_mounts


@pytest.fixture()
def corpus(tmp_path):
    """A stand-in for the read-only corpus mount, with one hidden entry."""
    root = tmp_path / "corpus"
    (root / "regression").mkdir(parents=True)
    (root / "abnormal").mkdir(parents=True)
    (root / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one")
    (root / "regression" / "doc02.pdf").write_bytes(b"%PDF-1.4 doc two")
    (root / "abnormal" / "corrupt.pdf").write_bytes(b"not a real pdf")
    (root / "notes.txt").write_text("plain text notes")
    (root / ".hidden").write_text("must be skipped")
    return root


@pytest.fixture()
def mounted(corpus, monkeypatch):
    """Serve the temporary corpus as the allowlisted 'corpus' mount."""
    monkeypatch.setattr(
        scan_handler, "get_settings", lambda: _Settings({"corpus": str(corpus)})
    )
    return corpus


def _make_root(
    db: Session,
    mount_id: str = "corpus",
    relative_path: str = ".",
    status: str = RootStatus.ACTIVE.value,
) -> str:
    root = AuthorizedRoot(
        mount_id=mount_id, relative_path=relative_path, status=status
    )
    db.add(root)
    db.commit()
    db.refresh(root)
    return root.id


def _count(db: Session, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _record(db: Session, relative_path: str) -> FileRecord:
    return db.execute(
        select(FileRecord).where(FileRecord.relative_path == relative_path)
    ).scalars().one()


def test_a_first_scan_records_files_versions_and_dispatches_jobs(mounted, db_session):
    root_id = _make_root(db_session)

    summary = handle_scan_root(db_session, root_id)

    assert summary["outcome"] == "scanned"
    # Four visible files; the dotfile is not one of them.
    assert summary["files_seen"] == 4
    assert summary["files_created"] == 4
    assert summary["versions_created"] == 4
    assert summary["jobs_dispatched"] == 4
    assert summary["files_missing"] == 0

    assert _count(db_session, FileRecord) == 4
    assert _count(db_session, FileVersion) == 4
    assert _count(db_session, Job) == 4

    pointed = db_session.execute(
        select(func.count())
        .select_from(FileRecord)
        .where(FileRecord.current_version_id.is_not(None))
    ).scalar_one()
    assert pointed == 4

    pending = db_session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.PENDING.value)
    ).scalar_one()
    assert pending == 4

    root = db_session.get(AuthorizedRoot, root_id)
    assert root.last_successful_scan_at is not None


def test_a_repeated_scan_creates_nothing_new(mounted, db_session):
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)

    summary = handle_scan_root(db_session, root_id)

    assert summary["files_seen"] == 4
    assert summary["files_created"] == 0
    assert summary["versions_created"] == 0
    assert summary["jobs_dispatched"] == 0
    assert summary["files_missing"] == 0
    assert _count(db_session, FileVersion) == 4
    assert _count(db_session, Job) == 4


def test_changed_content_versions_anew_and_moves_the_pointer(mounted, db_session):
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    first_version_id = _record(db_session, "regression/doc01.pdf").current_version_id

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one, revised")
    summary = handle_scan_root(db_session, root_id)

    assert summary["files_seen"] == 4
    assert summary["files_created"] == 0
    assert summary["versions_created"] == 1
    assert summary["jobs_dispatched"] == 1

    record = _record(db_session, "regression/doc01.pdf")
    assert record.current_version_id != first_version_id
    # The old row stays: history is never rewritten, only pointed past.
    assert _count(db_session, FileVersion) == 5


def test_a_missing_file_keeps_the_pointer_on_the_last_observed_version(
    mounted, db_session
):
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    version_id = _record(db_session, "regression/doc02.pdf").current_version_id

    (mounted / "regression" / "doc02.pdf").unlink()
    summary = handle_scan_root(db_session, root_id)

    assert summary["files_missing"] == 1
    record = _record(db_session, "regression/doc02.pdf")
    assert record.presence_status == FilePresence.MISSING.value
    assert record.current_version_id == version_id


def test_a_revoked_root_refuses_to_scan(mounted, db_session):
    root_id = _make_root(db_session, status=RootStatus.REVOKED.value)

    with pytest.raises(ValueError):
        handle_scan_root(db_session, root_id)


@pytest.mark.parametrize("relative_path", ["..", "/etc", "regression/../../escape"])
def test_a_root_pointing_outside_the_mount_is_rejected(
    mounted, db_session, relative_path: str
):
    root_id = _make_root(db_session, relative_path=relative_path)

    with pytest.raises(PathEscapesRoot):
        handle_scan_root(db_session, root_id)


def test_a_file_that_vanishes_between_walk_and_hash_skips_versioning(
    mounted, db_session, monkeypatch
):
    root_id = _make_root(db_session)
    real_identity = scan_handler.file_identity

    def flaky_identity(path):
        if Path(path).name == "doc02.pdf":
            raise SourceMissing(REASON_FILE_MISSING, "vanished mid-scan")
        return real_identity(path)

    monkeypatch.setattr(scan_handler, "file_identity", flaky_identity)

    summary = handle_scan_root(db_session, root_id)

    # Seen during the walk, but never versioned. There is no existing row to
    # mark missing either: the missing-file pass only touches files that were
    # observed on an earlier scan.
    assert summary["files_seen"] == 4
    assert summary["files_created"] == 3
    assert summary["versions_created"] == 3
    assert summary["jobs_dispatched"] == 3
    assert summary["files_missing"] == 0
    assert _count(db_session, FileRecord) == 3
    assert _count(db_session, FileVersion) == 3
