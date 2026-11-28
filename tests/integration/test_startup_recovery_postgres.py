"""Production transaction locks keep parallel model recovery single-flight."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.db import Base, make_engine
from services.common.models import Job
from services.search.indexing import index_document
from services.search.startup_recovery import queue_startup_embeddings
from tests.support.search import materialize_search_source

pytestmark = pytest.mark.postgres


def test_parallel_startup_recovery_skips_locked_version_then_observes_live_job(
    tmp_path, monkeypatch,
):
    url = os.environ.get("SEARCH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    monkeypatch.setattr(get_settings(), "source_mounts", {"search-fixtures": str(tmp_path)})
    engine = make_engine(url)
    schema = "c_startup_recovery_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        with Session(scoped, expire_on_commit=False) as first, Session(scoped) as second:
            version = index_document(
                first, file_id="parallel-recovery", name="source.pdf", path="source.pdf",
                chunks=[{"text": "Recovery source content", "page_number": 1}],
            )
            materialize_search_source(first, version)
            first.commit()
            assert queue_startup_embeddings(first) == 1
            # The first worker has not committed: a second transaction must not
            # block or create another job for the locked immutable version.
            assert queue_startup_embeddings(second) == 0
            second.rollback()
            first.commit()
            assert queue_startup_embeddings(second) == 0
            live = list(second.scalars(select(Job).where(Job.job_type == "embed_file")))
            assert len(live) == 1
            assert live[0].version_id == version.id
            assert live[0].status == "pending"
            second.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
