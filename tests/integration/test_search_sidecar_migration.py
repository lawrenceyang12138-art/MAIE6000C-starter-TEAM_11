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

REPO = Path(__file__).resolve().parents[2]


pytestmark = pytest.mark.postgres


def test_alembic_head_creates_both_search_sidecars():
    base_url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    database_name = "search_sidecar_migration_" + uuid.uuid4().hex
    admin_engine = create_engine(base_url)
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    scoped_url = make_url(base_url).set(database=database_name)
    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("script_location", str(REPO / "alembic"))
    config.attributes["database_url"] = scoped_url.render_as_string(hide_password=False)

    try:
        command.upgrade(config, "head")

        engine = create_engine(scoped_url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert {
                "source_chunks",
                "file_versions",
                "chunk_token_search_index",
                "version_page_search_metadata",
            } <= tables
        finally:
            engine.dispose()
    finally:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()
