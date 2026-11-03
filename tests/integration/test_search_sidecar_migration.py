"""Verify the additive C sidecars are part of the single Alembic chain."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
    VersionStatus,
    utcnow,
)
from services.search.page_metadata import (
    PAGE_METADATA_POLICY,
    VersionPageMetadata,
)
from services.search.text import MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS
from services.search.token_store import (
    ChunkTokenIndex,
    prepare_search_schema,
    text_fingerprint,
)

REPO = Path(__file__).resolve().parents[2]


pytestmark = pytest.mark.postgres


def _temporary_database(base_url: str):
    database_name = "search_sidecar_migration_" + uuid.uuid4().hex
    admin_engine = create_engine(base_url)
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    scoped_url = make_url(base_url).set(database=database_name)
    base_url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    return admin_engine, scoped_url, database_name


def _alembic_config(scoped_url) -> Config:
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("script_location", str(REPO / "alembic"))
    config.attributes["database_url"] = scoped_url.render_as_string(hide_password=False)
    return config


def _drop_database(admin_engine, database_name: str) -> None:
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    admin_engine.dispose()


def _seed_sidecar_data(engine, *, token: bool, metadata: bool) -> None:
    now = utcnow()
    with Session(engine) as session:
        root = AuthorizedRoot(
            id="root-migration",
            mount_id="migration",
            relative_path=".",
            status=RootStatus.ACTIVE.value,
        )
        record = FileRecord(
            id="file-migration",
            root_id=root.id,
            relative_path="manual.pdf",
            name="manual.pdf",
            presence_status=FilePresence.PRESENT.value,
            last_seen_at=now,
        )
        version = FileVersion(
            id="version-migration",
            file_id=record.id,
            content_sha256="a" * 64,
            byte_size=42,
            status=VersionStatus.BASIC_READY.value,
            parser_revision="parsing-v1",
        )
        chunk = SourceChunk(
            id="chunk-migration",
            version_id=version.id,
            ordinal=1,
            page_number=1,
            text="migration source text",
        )
        record.current_version_id = version.id
        session.add_all([root, record, version, chunk])
        session.flush()
        if token:
            session.add(
                ChunkTokenIndex(
                    chunk_id=chunk.id,
                    model_id=MODEL_ID,
                    model_revision=MODEL_REVISION,
                    token_dimensions=TOKEN_DIMENSIONS,
                    token_count=1,
                    token_vectors=[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)],
                    text_sha256=text_fingerprint(chunk.text),
                )
            )
        if metadata:
            session.add(
                VersionPageMetadata(
                    version_id=version.id,
                    content_sha256=version.content_sha256,
                    byte_size=version.byte_size,
                    parser_revision=version.parser_revision,
                    page_count=1,
                    policy_revision=PAGE_METADATA_POLICY,
                )
            )
        session.commit()


@pytest.mark.parametrize("existing", ["none", "both", "token_only", "metadata_only"])
def test_alembic_head_creates_missing_sidecars_and_preserves_existing_data(existing):
    base_url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    admin_engine, scoped_url, database_name = _temporary_database(base_url)
    config = _alembic_config(scoped_url)

    try:
        command.upgrade(config, "20261029_0004")
        engine = create_engine(scoped_url)
        if existing != "none":
            prepare_search_schema(engine)
        if existing == "token_only":
            VersionPageMetadata.__table__.drop(bind=engine)
        elif existing == "metadata_only":
            ChunkTokenIndex.__table__.drop(bind=engine)
        _seed_sidecar_data(
            engine,
            token=existing in {"both", "token_only"},
            metadata=existing in {"both", "metadata_only"},
        )

        command.upgrade(config, "head")
        try:
            tables = set(inspect(engine).get_table_names())
            assert {
                "source_chunks",
                "file_versions",
                "chunk_token_search_index",
                "version_page_search_metadata",
            } <= tables
            with Session(engine) as session:
                assert len(session.query(ChunkTokenIndex).all()) == int(
                    existing in {"both", "token_only"}
                )
                assert len(session.query(VersionPageMetadata).all()) == int(
                    existing in {"both", "metadata_only"}
                )
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_engine, database_name)


def test_populated_sidecars_allow_downgrade_and_upgrade_of_the_complete_chain():
    base_url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    admin_engine, scoped_url, database_name = _temporary_database(base_url)
    config = _alembic_config(scoped_url)
    engine = create_engine(scoped_url)
    try:
        command.upgrade(config, "head")
        _seed_sidecar_data(engine, token=True, metadata=True)
        command.downgrade(config, "20261029_0004")
        tables = set(inspect(engine).get_table_names())
        assert "chunk_token_search_index" not in tables
        assert "version_page_search_metadata" not in tables
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT id FROM source_chunks")) == "chunk-migration"
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM chunk_token_search_index")) == 0
            assert connection.scalar(text("SELECT count(*) FROM version_page_search_metadata")) == 0
        # These migrations used to fail when dropping source_chunks, because
        # the retained token sidecar still referenced it.
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert {"source_chunks", "chunk_token_search_index", "version_page_search_metadata"} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
        _drop_database(admin_engine, database_name)
