from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.common.config import get_settings
from services.common.db import Base, get_db, make_engine, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    VersionStatus,
)


@pytest.fixture(autouse=True)
def local_test_host(monkeypatch):
    """Starlette's in-process client uses testserver instead of a local socket."""
    settings = get_settings()
    monkeypatch.setattr(settings, "api_allowed_hosts", settings.api_allowed_hosts + ["testserver"])


@pytest.fixture()
def make_directory_link():
    """Create a directory link that leaves a tree, or skip if the OS refuses.

    A symlink is tried first. On Windows without developer mode that is denied
    without SeCreateSymbolicLinkPrivilege, so it falls back to a directory
    junction: no privilege needed, and the harder case anyway - ``is_symlink()``
    reports a junction as an ordinary directory, so only canonical resolution
    (and the reparse-point check in the scan) can catch it. Skipping is
    reported as a skip rather than passing quietly, because a containment test
    that creates nothing proves nothing.
    """

    def _make(link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                pytest.skip("this platform does not allow the test to create a link")
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
            )
            if result.returncode != 0 or not Path(link).exists():
                pytest.skip("this platform allows neither a symlink nor a junction")
        if not Path(link).exists():
            pytest.skip("the platform reported success but created no link")

    return _make


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    monkeypatch.setattr(
        get_settings(),
        "source_mounts",
        {
            "corpus": str(source_root / "corpus"),
            "search-fixtures": str(source_root / "search-fixtures"),
        },
    )
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(database_url)
    testing_session_factory = make_session_factory(engine)

    Base.metadata.create_all(bind=engine)
    session = testing_session_factory()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def make_file_version(db_session, monkeypatch):
    """Create the root -> file -> version chain a chunk row has to hang off.

    Every record is backed by a real temporary source file. Read paths now
    verify the source identity on every access, so a database-only fixture
    would no longer exercise the product boundary.
    """
    settings = get_settings()
    mount_root = Path(db_session.get_bind().url.database).parent / "source"
    monkeypatch.setattr(settings, "source_mounts", {"corpus": str(mount_root)})

    def _make(
        sha256: str | None = None,
        status: str = VersionStatus.DISCOVERED.value,
        source_path: str | Path | None = None,
    ) -> str:
        key = uuid4().hex
        root_dir = mount_root / f"root-{key}"
        root_dir.mkdir(parents=True)
        source = root_dir / "invoice.pdf"
        if source_path is None:
            source.write_bytes(f"temporary evidence source {sha256 or key}".encode())
        else:
            shutil.copyfile(source_path, source)

        source_bytes = source.read_bytes()
        content_sha256 = hashlib.sha256(source_bytes).hexdigest()
        root = AuthorizedRoot(
            mount_id="corpus",
            relative_path=root_dir.name,
            status=RootStatus.ACTIVE.value,
        )
        db_session.add(root)
        db_session.flush()

        file_record = FileRecord(
            root_id=root.id,
            relative_path=source.name,
            name="invoice.pdf",
            presence_status=FilePresence.PRESENT.value,
        )
        db_session.add(file_record)
        db_session.flush()

        version = FileVersion(
            file_id=file_record.id,
            content_sha256=content_sha256,
            byte_size=len(source_bytes),
            status=status,
        )
        db_session.add(version)
        db_session.commit()
        return version.id

    return _make
