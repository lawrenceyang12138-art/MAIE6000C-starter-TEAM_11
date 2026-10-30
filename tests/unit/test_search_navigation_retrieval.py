"""Navigation behavior over fixed vectors; these tests do not measure model quality."""

from __future__ import annotations

import math

import pytest
from sqlalchemy import select

from services.common.config import Settings
from services.common.models import AuthorizedRoot, FileRecord, SourceChunk
from services.common.schemas import SearchRequest
from services.parsing.evidence import read_evidence
from services.search.embeddings import EmbeddingUnavailable
from services.search.indexing import index_document as _index_document
from services.search.page_metadata import PAGE_METADATA_POLICY, VersionPageMetadata
from services.search.retrieval import search_chunks
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex
from tests.support.search import materialize_search_source


class ScoredBackend:
    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS

    def __init__(self):
        self.queries = []

    def embed(self, texts, kind="passage"):
        if kind == "query":
            self.queries.extend(texts)
            return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]
        scores = [float(text.split("score=")[1].split()[0]) for text in texts]
        return [
            [[score, math.sqrt(1 - score**2)] + [0.0] * (TOKEN_DIMENSIONS - 2)]
            for score in scores
        ]


def index_document(db, *args, **kwargs):
    version = _index_document(db, *args, **kwargs)
    materialize_search_source(db, version)
    return version


def document(db, backend, *, file_id="navigation", pages=(1, 2, 3), count=3,
             scores=(0.95, 0.8, 0.7), metadata=True):
    version = index_document(
        db, file_id=file_id, name="unseen.pdf", path=f"{file_id}/unseen.pdf",
        chunks=[
            {"text": f"archive evidence score={score} item={i}", "page_number": page}
            for i, (page, score) in enumerate(zip(pages, scores, strict=True))
        ], backend=backend,
    )
    if metadata:
        db.add(VersionPageMetadata(
            version_id=version.id, content_sha256=version.content_sha256,
            byte_size=version.byte_size, parser_revision=version.parser_revision,
            page_count=count, policy_revision=PAGE_METADATA_POLICY,
        ))
        db.flush()
    return version


def search(db, backend, *, query="archive last page", mode="semantic", enabled=True,
           **filters):
    diagnostics = {}
    response = search_chunks(
        db, SearchRequest(query=query, mode=mode, **filters),
        Settings(_env_file=None, search_page_navigation_enabled=enabled), backend,
        navigation_diagnostics=diagnostics,
    )
    return response, diagnostics


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_filter_precedes_file_selection_and_preserves_full_query_score_evidence(db_session, mode):
    backend = ScoredBackend()
    version = document(db_session, backend)
    query = "archive last page"
    ordinary, _ = search(db_session, backend, query=query, mode=mode, enabled=False)
    response, diagnostic = search(db_session, backend, query=query, mode=mode)
    assert ordinary.results[0].page == 1
    hit = response.results[0]
    assert hit.page == 3 and hit.semantic_score == 0.7
    assert backend.queries == [query, query]
    evidence = read_evidence(db_session, hit.chunk_id)
    assert (hit.version_id, hit.page, hit.text) == (
        version.id, evidence.page_number, evidence.text,
    )
    assert "physical page 3 of 3" in hit.reason
    assert not response.degraded
    decision = diagnostic["files"][0]
    assert decision["target_pages"] == [3] and decision["applied"]
    assert decision["selected_chunk_id"] == hit.chunk_id
    assert decision["selected_page"] == hit.page
    assert response.total == 1


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_even_middle_and_same_page_chunks_use_original_scores(db_session, mode):
    backend = ScoredBackend()
    document(db_session, backend, pages=(1, 2, 2, 3, 4), count=4,
             scores=(0.99, 0.6, 0.85, 0.8, 0.7))
    response, diagnostic = search(db_session, backend, query="archive middle page", mode=mode)
    hit = response.results[0]
    assert hit.page == 2 and hit.ordinal == 3 and hit.semantic_score == 0.85
    assert diagnostic["files"][0]["target_pages"] == [2, 3]
    assert diagnostic["files"][0]["target_chunk_count"] == 3


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize(("query", "count", "reason"), [
    ("archive last page", 4, "target_page_without_text_chunk"),
    ("archive page 9", 3, "page_out_of_range"),
])
def test_unavailable_target_never_returns_wrong_page_or_causes_ai_fallback(
    db_session, mode, query, count, reason,
):
    backend = ScoredBackend()
    document(db_session, backend, count=count)
    response, diagnostic = search(db_session, backend, query=query, mode=mode)
    assert response.results == [] and response.total == 0
    assert response.effective_mode == mode and not response.degraded
    assert diagnostic["files"][0]["reason"] == reason
    assert diagnostic["files"][0]["selected_page"] is None


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize("fault", ["missing", "schema_missing", "sha", "size", "parser", "policy"])
def test_unavailable_metadata_uses_ordinary_ranking_with_reason(db_session, mode, fault):
    backend = ScoredBackend()
    version = document(db_session, backend, metadata=fault not in {"missing", "schema_missing"})
    if fault == "schema_missing":
        VersionPageMetadata.__table__.drop(db_session.connection())
    elif fault not in {"missing", "schema_missing"}:
        metadata = db_session.get(VersionPageMetadata, version.id)
        field, value = {
            "sha": ("content_sha256", "f" * 64), "size": ("byte_size", 1),
            "parser": ("parser_revision", "incompatible"),
            "policy": ("policy_revision", "incompatible"),
        }[fault]
        setattr(metadata, field, value)
        db_session.flush()
    response, diagnostic = search(db_session, backend, mode=mode)
    status = f"page_metadata_{fault}" if fault in {"missing", "schema_missing"} else (
        "page_metadata_stale"
    )
    assert response.results[0].page == 1 and not response.degraded
    assert "page navigation not applied: " + status in response.results[0].reason
    assert not diagnostic["files"][0]["applied"]


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_unknown_page_does_not_impersonate_known_target(db_session, mode):
    backend = ScoredBackend()
    version = document(db_session, backend)
    last = db_session.scalar(select(SourceChunk).where(
        SourceChunk.version_id == version.id, SourceChunk.page_number == 3,
    ))
    last.page_number = None
    db_session.flush()
    response, diagnostic = search(db_session, backend, mode=mode)
    assert response.results == [] and not response.degraded
    assert diagnostic["files"][0]["reason"] == "target_page_without_text_chunk"


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_missing_target_vector_remains_explicitly_partial(db_session, mode):
    backend = ScoredBackend()
    version = document(db_session, backend)
    last = db_session.scalar(select(SourceChunk).where(
        SourceChunk.version_id == version.id, SourceChunk.page_number == 3,
    ))
    db_session.delete(db_session.get(ChunkTokenIndex, last.id))
    db_session.flush()
    response, diagnostic = search(db_session, backend, mode=mode)
    assert response.degraded and response.degradation_reason == "partial_embeddings"
    assert response.effective_mode == mode
    assert diagnostic["files"][0]["target_pages"] == [3]
    if mode == "semantic":
        assert response.results == []
    else:
        assert response.results[0].chunk_id == last.id
        assert response.results[0].page == 3 and response.results[0].semantic_score == 0


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize("reason", ["ai_disabled", "ai_unavailable", "ai_timeout"])
def test_ai_fallback_keeps_original_keyword_ranking_and_evidence(db_session, mode, reason):
    backend = ScoredBackend()
    document(db_session, backend)

    class FailingBackend(ScoredBackend):
        def embed(self, texts, kind="passage"):
            raise EmbeddingUnavailable(reason)

    diagnostics = {}
    response = search_chunks(
        db_session, SearchRequest(query="archive last page", mode=mode),
        Settings(_env_file=None, embedding_enabled=reason != "ai_disabled"),
        FailingBackend(), navigation_diagnostics=diagnostics,
    )
    assert response.mode == mode and response.effective_mode == "keyword"
    assert response.degraded and response.degradation_reason == reason
    assert response.results[0].page == 1
    assert response.results[0].semantic_score == 0
    assert read_evidence(db_session, response.results[0].chunk_id).text
    assert diagnostics["not_applied_reason"] == "ai_fallback:" + reason
    assert diagnostics["files"] == []


def test_search_never_opens_pdf_and_keyword_mode_does_not_apply_navigation(db_session, monkeypatch):
    backend = ScoredBackend()
    document(db_session, backend)

    def forbidden(*args, **kwargs):
        pytest.fail("search must only read metadata from the database")

    monkeypatch.setattr("services.search.page_metadata._read_physical_page_count", forbidden)
    monkeypatch.setattr("services.search.page_metadata.resolve_source_path", forbidden)
    monkeypatch.setattr("services.search.page_metadata.file_identity", forbidden)
    semantic, _ = search(db_session, backend)
    keyword, diagnostic = search(db_session, backend, mode="keyword")
    assert semantic.results[0].page == 3
    assert keyword.results[0].page == 1
    assert diagnostic["not_applied_reason"] == "keyword_mode"


@pytest.mark.parametrize("state", ["revoked", "missing", "superseded"])
def test_navigation_does_not_read_metadata_outside_eligible_current_scope(
    db_session, monkeypatch, state,
):
    backend = ScoredBackend()
    version = document(db_session, backend)
    record = db_session.get(FileRecord, version.file_id)
    if state == "revoked":
        db_session.get(AuthorizedRoot, record.root_id).status = "revoked"
    elif state == "missing":
        record.presence_status = "missing"
    else:
        record.current_version_id = None
    db_session.flush()

    def forbidden(*args, **kwargs):
        pytest.fail("metadata lookup must follow authorization and current-version filtering")

    monkeypatch.setattr("services.search.navigation_runtime.load_page_metadata", forbidden)
    response, diagnostic = search(db_session, backend)
    assert response.results == [] and diagnostic["files"] == []


def test_scope_same_name_dedup_and_page_filter_before_candidate_cap(db_session):
    backend = ScoredBackend()
    first = document(db_session, backend, file_id="one", scores=(0.99, 0.6, 0.5))
    second = document(db_session, backend, file_id="two", scores=(0.8, 0.7, 0.9))
    diagnostics = {}
    response = search_chunks(
        db_session, SearchRequest(query="archive last page", mode="hybrid"),
        Settings(_env_file=None).model_copy(update={"search_max_candidates": 1}), backend,
        navigation_diagnostics=diagnostics,
    )
    assert response.results[0].version_id == second.id and response.results[0].page == 3
    scoped, _ = search(db_session, backend, file_id=first.file_id)
    assert len(scoped.results) == 1 and scoped.results[0].version_id == first.id
    unscoped, _ = search(db_session, backend)
    assert len(unscoped.results) == 2
    assert len({hit.file_id for hit in unscoped.results}) == 2
    other_root = AuthorizedRoot(mount_id="other", relative_path=".", status="active")
    db_session.add(other_root)
    db_session.flush()
    rejected, diagnostic = search(db_session, backend, file_id=first.file_id, root_id=other_root.id)
    assert rejected.results == [] and diagnostic["files"] == []
