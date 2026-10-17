from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.common.db import Base, get_db, make_engine, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    VersionStatus,
)


@pytest.fixture()
def db_session(tmp_path):
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
def make_file_version(db_session):
    """Create the root -> file -> version chain a chunk row has to hang off.

    Root paths are unique per mount, so the chain is keyed off the content hash
    to keep the helper reusable for more than one version in a single test.
    """

    def _make(
        sha256: str = "a" * 64,
        status: str = VersionStatus.DISCOVERED.value,
    ) -> str:
        key = sha256[:8]
        root = AuthorizedRoot(
            mount_id=f"collection-{key}",
            relative_path=f"reports-{key}",
            status=RootStatus.ACTIVE.value,
        )
        db_session.add(root)
        db_session.flush()

        file_record = FileRecord(
            root_id=root.id,
            relative_path=f"reports-{key}/invoice.pdf",
            name="invoice.pdf",
            presence_status=FilePresence.PRESENT.value,
        )
        db_session.add(file_record)
        db_session.flush()

        version = FileVersion(
            file_id=file_record.id,
            content_sha256=sha256,
            byte_size=1234,
            status=status,
        )
        db_session.add(version)
        db_session.commit()
        return version.id

    return _make
