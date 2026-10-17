"""Authorized scanning, version reuse and extraction job creation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    RootJobType,
    RootStatus,
)
from services.scan.handler import (
    ScanPathError,
    resolve_authorized_root,
    scan_root,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def _root(db: Session, mount_path: Path, relative_path: str = "docs") -> AuthorizedRoot:
    root = AuthorizedRoot(
        mount_id="test",
        relative_path=relative_path,
        status=RootStatus.ACTIVE.value,
    )
    db.add(root)
    db.commit()
    return root


def test_scan_is_idempotent_and_creates_one_extract_job_per_version(
    db_session: Session, tmp_path: Path
):
    docs = tmp_path / "docs"
    nested = docs / "nested"
    nested.mkdir(parents=True)
    shutil.copy(FIXTURES / "normal.pdf", docs / "one.pdf")
    shutil.copy(FIXTURES / "normal.pdf", nested / "two.txt")
    (docs / ".hidden").write_text("skip me")
    root = _root(db_session, tmp_path)
    mounts = {"test": str(tmp_path)}

    first = scan_root(db_session, root, mounts)

    assert first.files_seen == 2
    assert first.files_created == 2
    assert first.versions_created == 2
    assert first.jobs_created == 2
    files = db_session.execute(select(FileRecord)).scalars().all()
    assert {file.relative_path for file in files} == {"one.pdf", "nested/two.txt"}
    assert all(file.current_version_id for file in files)
    assert all(file.presence_status == FilePresence.PRESENT.value for file in files)
    jobs = db_session.execute(select(Job)).scalars().all()
    assert len(jobs) == 2
    assert {job.job_type for job in jobs} == {RootJobType.EXTRACT_FILE.value}
    assert all(job.version_id for job in jobs)

    second = scan_root(db_session, root, mounts)

    assert second.files_seen == 2
    assert second.files_created == 0
    assert second.versions_created == 0
    assert second.jobs_created == 0
    assert len(db_session.execute(select(FileVersion)).scalars().all()) == 2
    assert len(db_session.execute(select(Job)).scalars().all()) == 2


def test_changed_and_missing_files_are_reconciled(
    db_session: Session, tmp_path: Path
):
    docs = tmp_path / "docs"
    docs.mkdir()
    one = docs / "one.pdf"
    two = docs / "two.pdf"
    shutil.copy(FIXTURES / "normal.pdf", one)
    shutil.copy(FIXTURES / "normal.pdf", two)
    root = _root(db_session, tmp_path)
    mounts = {"test": str(tmp_path)}
    scan_root(db_session, root, mounts)

    one.write_bytes(one.read_bytes() + b"\nchanged")
    two.unlink()

    summary = scan_root(db_session, root, mounts)

    assert summary.files_seen == 1
    assert summary.files_missing == 1
    assert summary.versions_created == 1
    assert summary.jobs_created == 1
    by_path = {
        file.relative_path: file
        for file in db_session.execute(select(FileRecord)).scalars().all()
    }
    assert by_path["one.pdf"].presence_status == FilePresence.PRESENT.value
    assert by_path["two.pdf"].presence_status == FilePresence.MISSING.value
    assert by_path["two.pdf"].current_version_id is not None


def test_symlink_escape_is_rejected(db_session: Session, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "linked").symlink_to(outside, target_is_directory=True)
    root = _root(db_session, tmp_path)

    summary = scan_root(db_session, root, {"test": str(tmp_path)})

    assert summary.files_seen == 0

    with pytest.raises(ScanPathError):
        resolve_authorized_root("test", "../outside", {"test": str(tmp_path)})

    with pytest.raises(ScanPathError):
        resolve_authorized_root("missing", "docs", {"test": str(tmp_path)})
