from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from services.api.app.main import app, get_embedding_backend
from services.common.config import Settings, get_settings
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    RootStatus,
    SourceChunk,
)
from services.search.embeddings import EmbeddingUnavailable
from services.search.evaluation import evaluate_queries
from services.search.indexing import embed_version, index_document
from services.search.text import DIMENSIONS, MODEL_ID


class ControlledEmbedding:
    """Stub only for failure/version/ranking tests; not semantic quality evidence."""

    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


class FailedEmbedding(ControlledEmbedding):
    def embed(self, texts, kind="passage"):
        raise EmbeddingUnavailable("ai_timeout")


def add_document(db, file_id="test-file", text="Database backup instructions", **kwargs):
    return index_document(
        db,
        file_id=file_id,
        name="manual.pdf",
        path=f"test/{file_id}.pdf",
        chunks=[{"text": text, "page_start": 2, "page_end": 3}],
        **kwargs,
    )


@pytest.fixture()
def keyword_only():
    app.dependency_overrides[get_settings] = lambda: Settings(
        embedding_enabled=False,
        _env_file=None,
    )


def test_keyword_page_evidence_and_file_deduplication(client, db_session):
    index_document(
        db_session,
        file_id="test-file",
        name="manual.pdf",
        path="test/manual.pdf",
        chunks=[
            {
                "text": "\u6570\u636e\u5e93\u5907\u4efd\u8bf4\u660e Database backup instructions",
                "page_start": 2,
                "page_end": 3,
            },
            {"text": "Database backup schedule", "page_start": 4, "page_end": 4},
        ],
    )
    response = client.post(
        "/search", json={"query": "\u6570\u636e\u5e93\u5907\u4efd", "mode": "keyword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["results"]) == 1
    hit = data["results"][0]
    assert (hit["file_id"], hit["page"], hit["ordinal"]) == ("test-file", 2, 1)
    assert hit["version_id"] and hit["chunk_id"] and hit["reason"] and hit["score"] > 0
    assert data["effective_mode"] == "keyword" and not data["degraded"]


def test_only_current_ready_unchanged_sources_are_searched(client, db_session):
    old = add_document(db_session, text="obsolete secret")
    current = add_document(db_session, text="current revision", version_number=2)
    source = db_session.get(FileRecord, "test-file")
    assert source.current_version_id == current.id and old.id != current.id
    assert (
        client.post("/search", json={"query": "obsolete", "mode": "keyword"}).json()["total"] == 0
    )
    assert client.post("/search", json={"query": "current", "mode": "keyword"}).json()["total"] == 1
    source.current_version_id = None
    db_session.flush()
    assert client.post("/search", json={"query": "current", "mode": "keyword"}).json()["total"] == 0


@pytest.mark.parametrize("mode", ["hybrid", "semantic"])
def test_ai_timeout_falls_back_to_keyword(client, db_session, mode):
    add_document(db_session)
    app.dependency_overrides[get_embedding_backend] = FailedEmbedding
    data = client.post("/search", json={"query": "backup", "mode": mode}).json()
    assert data["effective_mode"] == "keyword"
    assert data["degraded"] and data["degradation_reason"] == "ai_timeout"
    assert data["results"][0]["file_id"] == "test-file"


def test_disabled_ai_does_not_call_backend(client, db_session, keyword_only):
    add_document(db_session)
    app.dependency_overrides[get_embedding_backend] = FailedEmbedding
    data = client.post("/search", json={"query": "backup"}).json()
    assert data["degradation_reason"] == "ai_disabled"
    assert data["results"]


def test_semantic_and_hybrid_use_matching_version_vectors(client, db_session):
    add_document(db_session, text="unrelated wording", backend=ControlledEmbedding())
    app.dependency_overrides[get_embedding_backend] = ControlledEmbedding
    for mode in ["semantic", "hybrid"]:
        data = client.post("/search", json={"query": "different description", "mode": mode}).json()
        assert data["effective_mode"] == mode and not data["degraded"]
        assert data["results"][0]["semantic_score"] == 1.0


def test_missing_and_mismatched_vectors_fall_back(client, db_session):
    version = add_document(db_session, backend=ControlledEmbedding())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    db_session.get(ChunkSearchIndex, chunk.id).embedding_model = "old-model"
    db_session.flush()
    app.dependency_overrides[get_embedding_backend] = ControlledEmbedding
    data = client.post("/search", json={"query": "backup"}).json()
    assert data["degraded"] and data["degradation_reason"] == "embeddings_not_ready"
    assert data["results"][0]["semantic_score"] == 0.0


def test_file_filter_and_empty_result(client, db_session):
    add_document(db_session)
    assert (
        client.post(
            "/search",
            json={
                "query": "backup",
                "mode": "keyword",
                "file_id": "different-file",
            },
        ).json()["results"]
        == []
    )
    assert client.post("/search", json={"query": "qzxv", "mode": "keyword"}).json()["total"] == 0


def test_search_scope_intersects_root_and_file_and_allows_paused_roots(
    client, db_session
):
    add_document(db_session, file_id="scoped-file")
    file_record = db_session.get(FileRecord, "scoped-file")
    root = db_session.get(AuthorizedRoot, file_record.root_id)
    other_root = AuthorizedRoot(
        mount_id="other-fixture",
        relative_path=".",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(other_root)
    db_session.flush()

    base = {"query": "backup", "mode": "keyword", "file_id": file_record.id}
    assert client.post("/search", json={**base, "root_id": root.id}).json()["total"] == 1
    assert client.post("/search", json={**base, "root_id": other_root.id}).json()["total"] == 0

    root.status = RootStatus.PAUSED.value
    db_session.flush()
    assert client.post("/search", json={**base, "root_id": root.id}).json()["total"] == 1
    root.status = RootStatus.REVOKED.value
    db_session.flush()
    assert client.post("/search", json={**base, "root_id": root.id}).json()["total"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"query": " "},
        {"query": "x" * 501},
        {"query": "x", "top_k": 0},
        {"query": "x", "top_k": 51},
        {"query": "x", "mode": "invalid"},
    ],
)
def test_search_input_validation(client, payload):
    assert client.post("/search", json=payload).status_code == 422


def test_literal_sql_like_characters_cannot_return_all_documents(client, db_session):
    add_document(db_session)
    for query in ["%", "_", "' OR 1=1 --"]:
        assert client.post("/search", json={"query": query, "mode": "keyword"}).json()["total"] == 0


def test_idempotent_import_and_immutable_versions(db_session):
    first = add_document(db_session)
    second = add_document(db_session)
    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(SourceChunk)) == 1
    with pytest.raises(ValueError, match="immutable"):
        add_document(db_session, text="changed text", sha256=first.content_sha256)
    changed = add_document(db_session, text="changed text")
    assert changed.id != first.id
    assert db_session.scalar(
        select(SourceChunk.text).where(SourceChunk.version_id == first.id)
    ) == "Database backup instructions"


@pytest.mark.parametrize("existing_vectors", [False, True])
def test_failed_second_embedding_batch_keeps_text_and_existing_vectors(
    db_session, existing_vectors
):
    version = index_document(
        db_session,
        file_id="many-chunks",
        name="long.pdf",
        path="test/long.pdf",
        chunks=[{"text": f"Database backup item {i}", "chunk_index": i} for i in range(17)],
        backend=ControlledEmbedding() if existing_vectors else None,
    )
    chunks = list(
        db_session.scalars(
            select(SourceChunk)
            .where(SourceChunk.version_id == version.id)
            .order_by(SourceChunk.ordinal)
        )
    )
    indexes = [db_session.get(ChunkSearchIndex, chunk.id) for chunk in chunks]
    previous_vectors = [index.embedding for index in indexes]

    class FailSecondBatch(ControlledEmbedding):
        calls = 0

        def embed(self, texts, kind="passage"):
            self.calls += 1
            if self.calls == 2:
                raise EmbeddingUnavailable("ai_timeout")
            return super().embed(texts, kind)

    result = embed_version(db_session, version.id, FailSecondBatch())
    assert result.embedding_error == "ai_timeout" and result.embedded_count == 0
    assert len(chunks) == 17
    assert [index.embedding for index in indexes] == previous_vectors
    assert all(chunk.text for chunk in chunks)


def test_frozen_keyword_benchmark(client, db_session):
    root = Path(__file__).resolve().parents[2]
    fixture = json.loads((root / "fixtures/search/mock-chunks.json").read_text(encoding="utf-8"))
    gold = json.loads((root / "fixtures/search/gold-queries.json").read_text(encoding="utf-8"))
    for document in fixture["documents"]:
        index_document(db_session, **document)
    for query in gold["queries"][:5]:
        data = client.post("/search", json={"query": query["query"], "mode": "keyword"}).json()
        hit = data["results"][0]
        assert hit["file_id"] == query["expected_file_id"]
        assert hit["page"] == query["expected_page"]


def test_oversized_query_token_count_returns_422(client):
    query = " ".join(f"q{index}" for index in range(65))
    assert len(query) <= 500
    assert client.post("/search", json={"query": query, "mode": "keyword"}).status_code == 422


@pytest.mark.parametrize("mode", ["hybrid", "semantic"])
def test_partial_embeddings_are_explicit(client, db_session, mode):
    add_document(db_session, file_id="embedded", backend=ControlledEmbedding())
    add_document(db_session, file_id="text-only")
    app.dependency_overrides[get_embedding_backend] = ControlledEmbedding
    data = client.post("/search", json={"query": "backup", "mode": mode}).json()
    assert data["effective_mode"] == mode
    assert data["degraded"] and data["degradation_reason"] == "partial_embeddings"
    expected_files = {"embedded", "text-only"} if mode == "hybrid" else {"embedded"}
    assert {hit["file_id"] for hit in data["results"]} == expected_files


def test_partial_semantic_evaluation_cannot_pass(db_session):
    add_document(db_session, file_id="embedded", backend=ControlledEmbedding())
    add_document(db_session, file_id="text-only")
    gold = {
        "queries": [
            {
                "id": "partial-semantic",
                "kind": "semantic",
                "query": "backup",
                "expected_file_id": "embedded",
                "expected_page": 2,
            }
        ]
    }
    report = evaluate_queries(db_session, gold, Settings(_env_file=None), ControlledEmbedding())
    assert not report["passed"]
    assert report["summary"]["semantic_top3"] == "0/1"
    assert report["summary"]["degraded_queries"] == 1


def test_backfilling_old_version_does_not_replace_current(client, db_session):
    current = add_document(db_session, version_number=3, text="current backup")
    older = add_document(db_session, version_number=2, text="obsolete password")
    file_record = db_session.get(FileRecord, "test-file")
    file_record.current_version_id = current.id
    db_session.flush()
    assert older.id != current.id
    data = client.post("/search", json={"query": "backup", "mode": "keyword"}).json()
    assert data["results"][0]["version_id"] == current.id
    assert (
        client.post("/search", json={"query": "obsolete", "mode": "keyword"}).json()["total"] == 0
    )


def test_long_document_cannot_starve_other_files(client, db_session):
    index_document(
        db_session,
        file_id="long",
        name="long.pdf",
        path="test/long.pdf",
        chunks=[{"chunk_index": index, "text": "backup"} for index in range(210)],
    )
    add_document(db_session, file_id="short", text="backup")
    data = client.post("/search", json={"query": "backup", "mode": "keyword", "top_k": 2}).json()
    assert {hit["file_id"] for hit in data["results"]} == {"long", "short"}


def test_tied_evidence_keeps_first_source_page(client, db_session):
    index_document(
        db_session,
        file_id="tied-evidence",
        name="repeated.pdf",
        path="test/repeated.pdf",
        chunks=[
            {"text": "backup", "page_start": 1},
            {"text": "backup", "page_start": 3},
        ],
        backend=ControlledEmbedding(),
    )
    app.dependency_overrides[get_embedding_backend] = ControlledEmbedding
    for mode in ["keyword", "semantic", "hybrid"]:
        data = client.post("/search", json={"query": "backup", "mode": mode}).json()
        assert len(data["results"]) == 1
        assert data["results"][0]["page"] == 1
