"""Token retrieval behavior with hand-constructed vectors, not quality evidence."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import inspect, select

from services.common.config import Settings
from services.common.models import ChunkSearchIndex, SourceChunk
from services.common.schemas import SearchRequest
from services.parsing.evidence import read_evidence
from services.search.embeddings import EmbeddingUnavailable, late_interaction_score
from services.search.indexing import embed_version, index_document as _index_document
from services.search.retrieval import search_chunks
from services.search.text import DIMENSIONS, MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS
from services.search.token_store import (
    ChunkTokenIndex,
    compatible_index_predicate,
    index_matches_text,
    prepare_search_schema,
    text_fingerprint,
    token_index_available,
)
from tests.support.search import materialize_search_source


def token(*coordinates):
    return [*coordinates, *([0.0] * (TOKEN_DIMENSIONS - len(coordinates)))]


class HandConstructedBackend:
    model_id, dimensions = MODEL_ID, TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        if kind == "query":
            return [[token(1.0, 0.0), token(0.0, 1.0)] for _ in texts]
        return [
            [token(1.0, 0.0), token(0.0, 1.0)] if text == "separate concepts"
            else [token(1 / math.sqrt(2), 1 / math.sqrt(2))]
            for text in texts
        ]


def index_document(db, *args, **kwargs):
    version = _index_document(db, *args, **kwargs)
    materialize_search_source(db, version)
    return version


def add_document(db, *, file_id="document", text="separate concepts", backend=None):
    return index_document(
        db, file_id=file_id, name=f"{file_id}.pdf", path=f"manuals/{file_id}.pdf",
        chunks=[{"text": text, "page_number": 3}], backend=backend,
    )


def test_maxsim_distinguishes_token_interaction_from_mean_pooled_cosine(db_session):
    backend = HandConstructedBackend()
    query = backend.embed(["different query"], "query")[0]
    split, pooled = backend.embed(["separate concepts", "pooled concepts"])
    assert late_interaction_score(query, split) == pytest.approx(1.0)
    assert late_interaction_score(query, pooled) == pytest.approx(1 / math.sqrt(2))
    add_document(db_session, file_id="split", backend=backend)
    add_document(db_session, file_id="pooled", text="pooled concepts", backend=backend)
    result = search_chunks(
        db_session, SearchRequest(query="no lexical overlap", mode="semantic"),
        Settings(_env_file=None), backend,
    )
    assert not result.degraded
    assert [hit.file_id for hit in result.results] == ["split", "pooled"]
    assert result.results[0].keyword_score == 0
    assert result.embedding_dimensions == TOKEN_DIMENSIONS
    assert "MaxSim mean" in result.results[0].reason
    assert read_evidence(db_session, result.results[0].chunk_id).page_number == 3


def test_historical_dense_vectors_cannot_make_new_model_ready(db_session):
    version = add_document(db_session)
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    dense = db_session.get(ChunkSearchIndex, chunk.id)
    dense.embedding = [1.0] + [0.0] * (DIMENSIONS - 1)
    dense.embedding_model = MODEL_ID
    dense.embedding_dimensions = DIMENSIONS
    db_session.flush()
    result = search_chunks(
        db_session, SearchRequest(query="concepts", mode="semantic"),
        Settings(_env_file=None), HandConstructedBackend(),
    )
    assert result.effective_mode == "keyword" and result.degraded
    assert result.degradation_reason == "embeddings_not_ready"
    assert result.results[0].semantic_score == 0
    assert dense.embedding == [1.0] + [0.0] * (DIMENSIONS - 1)


def test_absent_token_table_degrades_without_implicit_read_ddl(db_session):
    add_document(db_session)
    db_session.commit()
    ChunkTokenIndex.__table__.drop(bind=db_session.connection())
    assert not token_index_available(db_session)
    result = search_chunks(
        db_session, SearchRequest(query="concepts", mode="hybrid"),
        Settings(_env_file=None), HandConstructedBackend(),
    )
    assert result.degradation_reason == "embeddings_not_ready"
    assert result.results[0].text == "separate concepts"
    assert not inspect(db_session.connection()).has_table(ChunkTokenIndex.__tablename__)
    prepare_search_schema(db_session.connection())
    assert token_index_available(db_session)


@pytest.mark.parametrize("invalid", ["text", "revision", "dimension", "count", "shape"])
def test_stale_or_malformed_token_rows_are_not_compatible(db_session, invalid):
    version = add_document(db_session, backend=HandConstructedBackend())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    index = db_session.get(ChunkTokenIndex, chunk.id)
    assert index_matches_text(index, chunk.text)
    if invalid == "text":
        index.text_sha256 = text_fingerprint("different bytes")
    elif invalid == "revision":
        index.model_revision = "older-revision"
    elif invalid == "dimension":
        index.token_dimensions = 1024
    elif invalid == "count":
        index.token_count += 1
    else:
        index.token_vectors = [[1.0]]
    db_session.flush()
    assert not index_matches_text(index, chunk.text)
    result = search_chunks(
        db_session, SearchRequest(query="concepts", mode="semantic"),
        Settings(_env_file=None), HandConstructedBackend(),
    )
    assert result.degraded and result.degradation_reason == "embeddings_not_ready"
    assert read_evidence(db_session, result.results[0].chunk_id).text == chunk.text


def test_json_token_roundtrip_and_source_chunk_delete_cascade(db_session):
    version = add_document(db_session, backend=HandConstructedBackend())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    chunk_id = chunk.id
    expected = HandConstructedBackend().embed([chunk.text])[0]
    db_session.commit()
    db_session.expire_all()
    retained = db_session.scalar(select(ChunkTokenIndex).where(compatible_index_predicate()))
    assert retained.chunk_id == chunk_id
    assert retained.token_vectors == expected
    assert retained.model_revision == MODEL_REVISION and retained.token_count == 2
    assert index_matches_text(retained, db_session.get(SourceChunk, chunk_id).text)
    db_session.delete(db_session.get(SourceChunk, chunk_id))
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(ChunkTokenIndex, chunk_id) is None


def test_maxsim_selects_the_correct_page_inside_a_file(db_session):
    version = index_document(
        db_session, file_id="located", name="located.pdf", path="manuals/located.pdf",
        chunks=[
            {"text": "pooled concepts", "page_number": 1},
            {"text": "separate concepts", "page_number": 2},
        ], backend=HandConstructedBackend(),
    )
    response = search_chunks(
        db_session, SearchRequest(query="different question", mode="semantic"),
        Settings(_env_file=None), HandConstructedBackend(),
    )
    assert not response.degraded and response.total == 1
    hit = response.results[0]
    assert hit.version_id == version.id and hit.page == 2
    assert read_evidence(db_session, hit.chunk_id).text == "separate concepts"


def test_semantic_chunk_volume_cannot_starve_other_files(db_session):
    backend = HandConstructedBackend()
    index_document(
        db_session, file_id="long", name="long.pdf", path="manuals/long.pdf",
        chunks=[{"text": "separate concepts", "page_number": page} for page in range(1, 211)],
        backend=backend,
    )
    add_document(db_session, file_id="short", text="pooled concepts", backend=backend)
    response = search_chunks(
        db_session, SearchRequest(query="different question", mode="semantic", top_k=2),
        Settings(_env_file=None), backend,
    )
    assert not response.degraded and response.total == 2
    assert [hit.file_id for hit in response.results] == ["long", "short"]
    assert response.results[0].page == 1


def test_failed_new_embedding_keeps_tokens_and_keyword_but_clears_retired_dense(db_session):
    version = add_document(db_session, backend=HandConstructedBackend())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    retained = db_session.get(ChunkTokenIndex, chunk.id)
    previous = [list(row) for row in retained.token_vectors]
    dense = db_session.get(ChunkSearchIndex, chunk.id)
    dense.embedding = [1.0] + [0.0] * (DIMENSIONS - 1)
    dense.embedding_model = "retired-dense-model"
    dense.embedding_dimensions = DIMENSIONS
    db_session.commit()

    class DisconnectedBackend(HandConstructedBackend):
        def embed(self, texts, kind="passage"):
            raise EmbeddingUnavailable("ai_unavailable")

    result = embed_version(db_session, version.id, DisconnectedBackend())
    db_session.commit()
    assert result.embedding_error == "ai_unavailable" and result.embedded_count == 0
    assert retained.token_vectors == previous and index_matches_text(retained, chunk.text)
    assert dense.embedding is None and dense.embedding_model is None
    assert dense.embedding_dimensions is None and dense.search_text == "separate concepts"
    assert read_evidence(db_session, chunk.id).text == "separate concepts"


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_nearby_maxsim_scores_rank_before_public_rounding(db_session, mode):
    class NearbyScoresBackend(HandConstructedBackend):
        def embed(self, texts, kind="passage"):
            if kind == "query":
                return [[token(1.0, 0.0)] for _ in texts]
            similarities = [0.8000002 if "weaker" in text else 0.8000004 for text in texts]
            return [[token(value, math.sqrt(1 - value * value))] for value in similarities]

    backend = NearbyScoresBackend()
    add_document(db_session, file_id="a-weaker", text="weaker evidence", backend=backend)
    add_document(db_session, file_id="z-stronger", text="stronger evidence", backend=backend)
    response = search_chunks(
        db_session, SearchRequest(query="different question", mode=mode, top_k=2),
        Settings(_env_file=None), backend,
    )
    assert not response.degraded
    assert [hit.file_id for hit in response.results] == ["z-stronger", "a-weaker"]
    assert response.results[0].score == response.results[1].score
    first_only = search_chunks(
        db_session, SearchRequest(query="different question", mode=mode, top_k=1),
        Settings(_env_file=None), backend,
    )
    assert first_only.results[0].file_id == "z-stronger"


@pytest.mark.parametrize("distractor_count", [0, 51])
def test_hybrid_selects_combined_winner_before_file_limit(db_session, distractor_count):
    class DifferentChannelWinnersBackend(HandConstructedBackend):
        def embed(self, texts, kind="passage"):
            if kind == "query":
                return [[token(1.0, 0.0)] for _ in texts]
            similarities = {"alpha beta": 0.1, "beta alongside alpha": 0.9}
            values = [similarities.get(text, 1.0) for text in texts]
            return [[token(value, math.sqrt(1 - value * value))] for value in values]

    backend = DifferentChannelWinnersBackend()
    version = index_document(
        db_session, file_id="combined-winner", name="winner.pdf", path="manuals/winner.pdf",
        chunks=[
            {"text": "alpha beta", "page_number": 1},
            {"text": "unrelated", "page_number": 2},
            {"text": "beta alongside alpha", "page_number": 3},
        ], backend=backend,
    )
    for position in range(distractor_count):
        add_document(
            db_session, file_id=f"distractor-{position}", text="unrelated", backend=backend,
        )
    response = search_chunks(
        db_session, SearchRequest(query="alpha beta", mode="hybrid", top_k=1),
        Settings(_env_file=None, search_max_candidates=50), backend,
    )
    assert not response.degraded
    hit = response.results[0]
    assert hit.file_id == "combined-winner" and hit.version_id == version.id
    assert hit.page == 3
    assert hit.keyword_score == pytest.approx(0.8)
    assert hit.semantic_score == pytest.approx(0.9)
    assert hit.score == pytest.approx(0.835)
    assert read_evidence(db_session, hit.chunk_id).text == "beta alongside alpha"


def test_partial_hybrid_retains_keyword_only_file_and_readable_evidence(db_session):
    backend = HandConstructedBackend()
    keyword_version = add_document(db_session, file_id="keyword-only", text="alpha beta")
    add_document(db_session, file_id="embedded", backend=backend)
    response = search_chunks(
        db_session, SearchRequest(query="alpha beta", mode="hybrid", top_k=2),
        Settings(_env_file=None), backend,
    )
    assert response.degraded and response.degradation_reason == "partial_embeddings"
    assert response.effective_mode == "hybrid"
    assert [hit.file_id for hit in response.results] == ["keyword-only", "embedded"]
    hit = response.results[0]
    assert hit.version_id == keyword_version.id
    assert hit.keyword_score == 1 and hit.semantic_score == 0 and hit.score == 0.65
    assert read_evidence(db_session, hit.chunk_id).text == "alpha beta"
