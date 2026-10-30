from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.db import Base, make_engine
from services.common.models import ChunkSearchIndex, SourceChunk
from services.common.schemas import SearchRequest
from services.search.indexing import index_document
from services.search.retrieval import search_chunks
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex, prepare_search_schema

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
    dimensions = TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]


def test_postgres_chinese_english_and_pgvector(postgres_session):
    db = postgres_session
    index_document(
        db,
        file_id="pg-test",
        name="manual.pdf",
        path="synthetic/manual.pdf",
        chunks=[
            {
                "text": "\u6570\u636e\u5e93\u5907\u4efd Database backup guide",
                "page_start": 2,
                "page_end": 3,
            }
        ],
        backend=FixedBackend(),
    )
    settings = Settings(_env_file=None)
    for mode, query in [
        ("keyword", "\u6570\u636e\u5e93\u5907\u4efd"),
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


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_postgres_missing_sidecar_reports_partial_embeddings(postgres_session, mode):
    db = postgres_session
    for file_id in ["pg-indexed", "pg-unindexed"]:
        version = index_document(
            db,
            file_id=file_id,
            name="manual.pdf",
            path=f"{file_id}/manual.pdf",
            chunks=[{"text": "Database backup", "page_number": 2}],
            backend=FixedBackend(),
        )
        if file_id == "pg-unindexed":
            chunk = db.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
            db.delete(db.get(ChunkSearchIndex, chunk.id))
    db.flush()
    response = search_chunks(
        db, SearchRequest(query="backup", mode=mode), Settings(_env_file=None), FixedBackend()
    )
    assert response.effective_mode == mode
    assert response.degraded and response.degradation_reason == "partial_embeddings"
    assert {hit.file_id for hit in response.results} == {"pg-indexed"}


def test_postgres_explicit_token_schema_preserves_dense_vector_dimension(postgres_session):
    db = postgres_session
    connection = db.connection()
    ChunkTokenIndex.__table__.drop(bind=connection)
    prepare_search_schema(connection)
    vector_type = db.scalar(text(
        "SELECT format_type(a.atttypid,a.atttypmod) "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname='chunk_search_index' "
        "AND a.attname='embedding'"
    ))
    token_type = db.scalar(text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema=current_schema() AND table_name='chunk_token_search_index' "
        "AND column_name='token_vectors'"
    ))
    assert vector_type == "vector(384)"
    assert token_type == "jsonb"
    version = index_document(
        db, file_id="token-jsonb", name="manual.pdf", path="token/manual.pdf",
        chunks=[{"text": "Database backup", "page_number": 2}], backend=FixedBackend(),
    )
    db.flush()
    chunk = db.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    db.expire_all()
    retained = db.get(ChunkTokenIndex, chunk.id)
    assert retained.token_dimensions == TOKEN_DIMENSIONS
    assert retained.token_vectors == FixedBackend().embed(["Database backup"])[0]
    response = search_chunks(
        db, SearchRequest(query="restore records", mode="semantic"),
        Settings(_env_file=None), FixedBackend(),
    )
    assert not response.degraded and response.results[0].chunk_id == chunk.id
