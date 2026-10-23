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
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

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
)
from services.parsing.pdf import REASON_FILE_MISSING, SourceMissing
from services.scan import handler as scan_handler
from services.scan.handler import PathEscapesRoot, handle_scan_root, resolve_source_path


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


def test_reverting_to_earlier_content_moves_the_pointer_back(mounted, db_session):
    """A revert to content we already hold must point at the bytes on disk.

    Without this, ``current_version_id`` keeps naming the revised version, so
    evidence for the version actually on disk answers ``409 version_superseded``
    while evidence for the superseded version answers 200 with text the file no
    longer contains (D1: the pointer means latest observed content).
    """
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    original = _record(db_session, "regression/doc01.pdf").current_version_id

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one, revised")
    handle_scan_root(db_session, root_id)
    assert _record(db_session, "regression/doc01.pdf").current_version_id != original

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one")
    summary = handle_scan_root(db_session, root_id)

    assert _record(db_session, "regression/doc01.pdf").current_version_id == original
    assert summary["versions_created"] == 0
    assert summary["pointers_restored"] == 1
    # No new row: the reverted content is the version we already had.
    assert _count(db_session, FileVersion) == 5


def test_a_revert_does_not_redispatch_a_processed_version(mounted, db_session):
    """Reverting is pointer bookkeeping, not new work (§3.4.6 idempotency)."""
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    original = _record(db_session, "regression/doc01.pdf").current_version_id

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one, revised")
    handle_scan_root(db_session, root_id)

    version = db_session.get(FileVersion, original)
    version.status = VersionStatus.BASIC_READY.value
    db_session.commit()

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one")
    summary = handle_scan_root(db_session, root_id)

    assert _record(db_session, "regression/doc01.pdf").current_version_id == original
    assert summary["jobs_dispatched"] == 0
    # Four first-scan jobs plus the one for the revised version; the revert adds none.
    assert _count(db_session, Job) == 5


def test_a_revert_redispatches_a_version_that_never_finished(mounted, db_session):
    """A ``discovered`` version with no live job is recovered, not orphaned."""
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    original = _record(db_session, "regression/doc01.pdf").current_version_id

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one, revised")
    handle_scan_root(db_session, root_id)

    # Simulate a lost extract job: the version is still discovered, the job is gone.
    db_session.execute(delete(Job).where(Job.version_id == original))
    db_session.commit()

    (mounted / "regression" / "doc01.pdf").write_bytes(b"%PDF-1.4 doc one")
    summary = handle_scan_root(db_session, root_id)

    assert summary["versions_created"] == 0
    assert summary["jobs_dispatched"] == 1
    live = db_session.execute(
        select(Job).where(
            Job.version_id == original,
            Job.job_type == "extract_file",
            Job.status == JobStatus.PENDING.value,
        )
    ).scalars().all()
    assert len(live) == 1


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


def test_a_second_scan_of_a_live_root_is_skipped(mounted, db_session):
    """The job id lets the handler stand down when another scan is unfinished.

    Without this, two queued scans of one folder would walk it twice and the
    later one could publish a summary from a half-changed tree.
    """
    root_id = _make_root(db_session)
    db_session.add(
        Job(
            root_id=root_id,
            job_type=RootJobType.SCAN_ROOT.value,
            status=JobStatus.PENDING.value,
        )
    )
    db_session.commit()
    mine = Job(
        root_id=root_id,
        job_type=RootJobType.SCAN_ROOT.value,
        status=JobStatus.CLAIMED.value,
    )
    db_session.add(mine)
    db_session.commit()

    summary = handle_scan_root(db_session, root_id, mine.id)

    assert summary["outcome"] == "skipped"
    assert summary["root_id"] == root_id
    # Nothing was observed, versioned or dispatched.
    assert _count(db_session, FileRecord) == 0
    assert _count(db_session, FileVersion) == 0
    assert _count(db_session, Job) == 2


def _make_symlink(link: Path, target: Path) -> None:
    """Create a directory symlink, or skip where the platform refuses.

    Some Windows setups neither raise nor create anything: ``symlink_to``
    returns quietly and the path stays absent. Without the second check the
    escape tests would pass while exercising nothing, which is worse than a
    skip - the evidence must show that the case really ran.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow the test to create a symlink")
    if not link.is_symlink():
        pytest.skip("this platform reported success but created no symlink")


def test_a_symlinked_directory_inside_the_root_is_not_followed(
    mounted, tmp_path, db_session
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4 outside the mount")
    _make_symlink(mounted / "linked", outside)

    root_id = _make_root(db_session)
    summary = handle_scan_root(db_session, root_id)

    # The four real files are still seen; the link is neither entered nor read.
    assert summary["files_seen"] == 4
    paths = {
        record.relative_path
        for record in db_session.execute(select(FileRecord)).scalars()
    }
    assert paths == {
        "regression/doc01.pdf",
        "regression/doc02.pdf",
        "abnormal/corrupt.pdf",
        "notes.txt",
    }


def test_a_root_that_is_a_symlink_outside_the_mount_is_rejected(
    mounted, tmp_path, db_session
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4 outside the mount")
    _make_symlink(mounted / "escape", outside)

    root_id = _make_root(db_session, relative_path="escape")

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


def _set_root_status(db: Session, root_id: str, status: str) -> None:
    root = db.get(AuthorizedRoot, root_id)
    root.status = status
    db.commit()


def _version_id_of(db: Session, relative_path: str) -> str:
    return _record(db, relative_path).current_version_id


def test_resolving_a_source_path_allows_a_paused_root_for_reads(mounted, db_session):
    """Pausing stops new jobs; it does not hide content that is already indexed."""
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    version_id = _version_id_of(db_session, "regression/doc01.pdf")
    _set_root_status(db_session, root_id, RootStatus.PAUSED.value)

    resolved = resolve_source_path(db_session, version_id, for_write=False)

    assert resolved == (mounted / "regression" / "doc01.pdf").resolve()


def test_resolving_a_source_path_refuses_a_paused_root_for_new_work(
    mounted, db_session
):
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    version_id = _version_id_of(db_session, "regression/doc01.pdf")
    _set_root_status(db_session, root_id, RootStatus.PAUSED.value)

    with pytest.raises(PathEscapesRoot):
        resolve_source_path(db_session, version_id)


@pytest.mark.parametrize(
    "status", [RootStatus.REVOKING.value, RootStatus.REVOKED.value]
)
def test_resolving_a_source_path_refuses_a_revoked_root_for_reads(
    mounted, db_session, status: str
):
    root_id = _make_root(db_session)
    handle_scan_root(db_session, root_id)
    version_id = _version_id_of(db_session, "regression/doc01.pdf")
    _set_root_status(db_session, root_id, status)

    with pytest.raises(PathEscapesRoot):
        resolve_source_path(db_session, version_id, for_write=False)
