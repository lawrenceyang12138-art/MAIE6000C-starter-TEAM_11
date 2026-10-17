"""The real worker path from scan_root through extract_file."""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
    VersionStatus,
)
from services.worker.app import main as worker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def test_worker_scans_and_processes_supported_and_unsupported_files(
    db_session: Session, tmp_path: Path, monkeypatch
):
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(FIXTURES / "normal.pdf", docs / "normal.pdf")
    shutil.copy(FIXTURES.parent / "regression" / "unsupported.txt", docs / "notes.txt")

    root = AuthorizedRoot(
        mount_id="test",
        relative_path="docs",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(root)
    db_session.flush()
    scan_job = Job(
        root_id=root.id,
        job_type=RootJobType.SCAN_ROOT.value,
        status=JobStatus.PENDING.value,
    )
    db_session.add(scan_job)
    db_session.commit()

    monkeypatch.setattr(worker.settings, "source_mounts", {"test": str(tmp_path)})
    monkeypatch.setattr(
        worker,
        "get_session_factory",
        lambda: lambda: contextlib.nullcontext(db_session),
    )

    worker.process_job(scan_job.id)

    db_session.expire_all()
    assert db_session.get(Job, scan_job.id).status == JobStatus.COMPLETED.value
    files = db_session.execute(select(FileRecord)).scalars().all()
    assert {file.name for file in files} == {"normal.pdf", "notes.txt"}
    assert all(file.current_version_id is not None for file in files)

    extract_jobs = (
        db_session.execute(
            select(Job).where(Job.job_type == RootJobType.EXTRACT_FILE.value)
        )
        .scalars()
        .all()
    )
    assert len(extract_jobs) == 2

    for job in extract_jobs:
        worker.process_job(job.id)

    db_session.expire_all()
    versions = db_session.execute(select(FileVersion)).scalars().all()
    statuses = {version.status for version in versions}
    assert VersionStatus.BASIC_READY.value in statuses
    assert VersionStatus.UNSUPPORTED.value in statuses
    assert all(
        db_session.get(Job, job.id).status == JobStatus.COMPLETED.value
        for job in extract_jobs
    )
