from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.db import Base, make_engine
from services.common.schemas import SearchRequest
from services.search.indexing import index_document
from services.search.retrieval import search_chunks
from services.search.text import DIMENSIONS, MODEL_ID

pytestmark = pytest.mark.postgres


@pytest.fixture()
def postgres_session():
    url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")
    engine = make_engine(url)
    schema = "c_search_test_" + uuid.uuid4().hex
    with engine.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection = connection.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(connection)
        connection.commit()
        try:
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()


class FixedBackend:
    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


def test_postgres_chinese_english_and_pgvector(postgres_session):
    db = postgres_session
    index_document(
        db,
        file_id="pg-test",
        name="manual.pdf",
        path="synthetic/manual.pdf",
        chunks=[{"text": "数据库备份 Database backup guide", "page_start": 2, "page_end": 3}],
        backend=FixedBackend(),
    )
    settings = Settings(_env_file=None)
    for mode, query in [
        ("keyword", "数据库备份"),
        ("keyword", "backup"),
        ("semantic", "recover lost records"),
        ("hybrid", "backup"),
    ]:
        response = search_chunks(
            db, SearchRequest(query=query, mode=mode), settings, FixedBackend()
        )
        assert not response.degraded
        assert response.results[0].file_id == "pg-test"
        assert response.results[0].page == 2
    index_exists = db.scalar(
        text(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() "
            "AND indexname = 'ix_chunk_search_index_keyword' AND indexdef LIKE '%gin%'"
        )
    )
    assert index_exists == 1


def test_postgres_current_version_unique_and_old_text_hidden(postgres_session):
    db = postgres_session
    for number, words in [(1, "obsolete secret"), (2, "current backup")]:
        index_document(
            db,
            file_id="pg-file",
            name="guide.pdf",
            path="synthetic/guide.pdf",
            version_number=number,
            chunks=[{"text": words}],
        )
    result = search_chunks(
        db, SearchRequest(query="obsolete", mode="keyword"), Settings(_env_file=None), None
    )
    assert result.results == []
    current_count = db.scalar(
        text(
            "SELECT count(*) FROM files WHERE current_version_id IN "
            "(SELECT id FROM file_versions WHERE file_id = 'pg-file')"
        )
    )
    assert current_count == 1
