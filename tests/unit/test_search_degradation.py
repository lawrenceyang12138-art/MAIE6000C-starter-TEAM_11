"""Failure isolation and source eligibility; fixed vectors are not quality evidence."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from services.common.config import Settings
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    SourceChunk,
)
from services.common.schemas import SearchRequest
from services.parsing.evidence import read_evidence
from services.search.embeddings import (
    EmbeddingUnavailable,
    HTTPEmbeddingBackend,
    LocalE5EmbeddingBackend,
)
from services.search.indexing import embed_version, index_document
from services.search.retrieval import search_chunks
from services.search.text import DIMENSIONS, MODEL_ID


class FixedBackend:
    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


def add_document(db, file_id="document", **kwargs):
    return index_document(
        db,
        file_id=file_id,
        name="recovery.pdf",
        path=f"manuals/{file_id}.pdf",
        chunks=[{"text": "Database backup recovery instructions", "page_number": 2}],
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize(
    ("error_type", "reason"),
    [(httpx.ConnectError, "ai_unavailable"), (httpx.ReadTimeout, "ai_timeout")],
)
def test_http_failure_preserves_requested_mode_keyword_and_evidence(
    db_session, monkeypatch, mode, error_type, reason
):
    version = add_document(db_session, backend=FixedBackend())

    def fail_http(*args, **kwargs):
        assert kwargs["timeout"] == 0.125
        assert kwargs["trust_env"] is False
        raise error_type("private connection details must not be exposed")

    monkeypatch.setattr(httpx, "post", fail_http)
    response = search_chunks(
        db_session,
        SearchRequest(query="backup", mode=mode),
        Settings(_env_file=None),
        HTTPEmbeddingBackend("http://127.0.0.1:8100", timeout=0.125),
    )
    assert response.mode == mode
    assert response.effective_mode == "keyword"
    assert response.degraded and response.degradation_reason == reason
    assert response.embedding_model is None
    assert len(response.results) == 1
    hit = response.results[0]
    evidence = read_evidence(db_session, hit.chunk_id)
    assert hit.keyword_score > 0 and hit.semantic_score == 0
    assert (hit.file_id, hit.version_id, hit.page, hit.text) == (
        evidence.file_id,
        version.id,
        evidence.page_number,
        evidence.text,
    )
    assert evidence.content_sha256 == version.content_sha256


def test_missing_local_model_explicitly_degrades_without_losing_source(db_session, tmp_path):
    add_document(db_session)
    response = search_chunks(
        db_session,
        SearchRequest(query="backup", mode="semantic"),
        Settings(_env_file=None),
        LocalE5EmbeddingBackend(str(tmp_path / "missing-model")),
    )
    assert response.mode == "semantic" and response.effective_mode == "keyword"
    assert response.degradation_reason == "local_model_missing"
    assert read_evidence(db_session, response.results[0].chunk_id).text


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize("fault", ["model", "dimensions", "vector"])
def test_incompatible_query_vectors_preserve_keyword_evidence(db_session, mode, fault):
    add_document(db_session, backend=FixedBackend())

    class IncompatibleBackend(FixedBackend):
        model_id = "wrong-revision" if fault == "model" else MODEL_ID
        dimensions = 8 if fault == "dimensions" else DIMENSIONS

        def embed(self, texts, kind="passage"):
            return [[0.0] * DIMENSIONS for _ in texts]

    response = search_chunks(
        db_session,
        SearchRequest(query="backup", mode=mode),
        Settings(_env_file=None),
        IncompatibleBackend(),
    )
    reason = "invalid_embedding_response" if fault == "vector" else "embedding_model_mismatch"
    assert response.mode == mode and response.effective_mode == "keyword"
    assert response.degraded and response.degradation_reason == reason
    assert response.results[0].semantic_score == 0.0
    assert read_evidence(db_session, response.results[0].chunk_id).text


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
def test_missing_sidecar_is_partial_and_readiness_obeys_root_scope(db_session, mode):
    add_document(db_session, file_id="embedded", backend=FixedBackend())
    unindexed = add_document(db_session, file_id="unindexed")
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == unindexed.id))
    db_session.delete(db_session.get(ChunkSearchIndex, chunk.id))
    db_session.flush()
    settings = Settings(_env_file=None)
    request = SearchRequest(query="backup", mode=mode)
    response = search_chunks(db_session, request, settings, FixedBackend())
    assert response.effective_mode == mode
    assert response.degraded and response.degradation_reason == "partial_embeddings"

    # The same missing index in a different, unselected root is not a reason to
    # mark the selected root incomplete, and revoked roots are also excluded.
    embedded = db_session.get(FileRecord, "embedded")
    second_root = AuthorizedRoot(mount_id="second-corpus", relative_path=".", status="active")
    db_session.add(second_root)
    db_session.flush()
    db_session.get(FileRecord, "unindexed").root_id = second_root.id
    db_session.flush()
    scoped = search_chunks(
        db_session,
        request.model_copy(update={"root_id": embedded.root_id}),
        settings,
        FixedBackend(),
    )
    assert not scoped.degraded
    second_root.status = "revoked"
    db_session.flush()
    assert not search_chunks(db_session, request, settings, FixedBackend()).degraded


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
@pytest.mark.parametrize(
    ("target", "state", "visible"),
    [
        ("root", "active", True),
        ("root", "paused", True),
        ("root", "revoking", False),
        ("root", "revoked", False),
        ("file", "present", True),
        ("file", "missing", False),
        ("file", "unavailable", False),
        ("version", "enriched", True),
        ("version", "discovered", False),
        ("version", "extracting", False),
        ("version", "failed", False),
    ],
)
def test_all_modes_filter_source_state(db_session, mode, target, state, visible):
    version = add_document(db_session, backend=FixedBackend())
    file_record = db_session.get(FileRecord, "document")
    if target == "root":
        db_session.get(AuthorizedRoot, file_record.root_id).status = state
    elif target == "file":
        file_record.presence_status = state
    else:
        version.status = state
    db_session.flush()
    response = search_chunks(
        db_session,
        SearchRequest(query="backup", mode=mode),
        Settings(_env_file=None),
        FixedBackend(),
    )
    assert bool(response.results) is visible
    if visible:
        assert read_evidence(db_session, response.results[0].chunk_id).version_id == version.id


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_file_filter_intersects_authorized_root_in_all_modes(db_session, mode):
    add_document(db_session, backend=FixedBackend())
    file_record = db_session.get(FileRecord, "document")
    other_root = AuthorizedRoot(mount_id="other-mount", relative_path=".", status="active")
    db_session.add(other_root)
    db_session.flush()
    settings = Settings(_env_file=None)
    request = SearchRequest(
        query="backup", mode=mode, file_id=file_record.id, root_id=file_record.root_id
    )
    assert search_chunks(db_session, request, settings, FixedBackend()).total == 1
    assert search_chunks(
        db_session,
        request.model_copy(update={"root_id": other_root.id}),
        settings,
        FixedBackend(),
    ).results == []


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_dedup_keeps_distinct_paths_and_current_evidence(db_session, mode):
    for file_id in ["copy-one", "copy-two"]:
        index_document(
            db_session,
            file_id=file_id,
            name="same-name.pdf",
            path=f"{file_id}/same-name.pdf",
            sha256="a" * 64,
            chunks=[{"text": "Database backup", "page_number": page} for page in [1, 2, 3]],
            backend=FixedBackend(),
        )
    response = search_chunks(
        db_session,
        SearchRequest(query="backup", mode=mode),
        Settings(_env_file=None),
        FixedBackend(),
    )
    assert response.total == 2
    assert {hit.file_id for hit in response.results} == {"copy-one", "copy-two"}
    assert all(hit.page == 1 for hit in response.results)
    for hit in response.results:
        evidence = read_evidence(db_session, hit.chunk_id)
        assert evidence.version_id == hit.version_id and evidence.page_number == hit.page


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_new_unparsed_current_version_does_not_expose_old_chunks(db_session, mode):
    old = add_document(db_session, backend=FixedBackend())
    current = index_document(
        db_session,
        file_id="document",
        name="recovery.pdf",
        path="manuals/document.pdf",
        chunks=[{"text": "backup procedure changed", "page_number": 4}],
        backend=FixedBackend(),
    )
    assert current.id != old.id
    request = SearchRequest(query="backup", mode=mode)
    settings = Settings(_env_file=None)
    response = search_chunks(db_session, request, settings, FixedBackend())
    assert len(response.results) == 1
    assert response.results[0].version_id == current.id
    assert response.results[0].page == 4
    current.status = "discovered"
    db_session.flush()
    assert search_chunks(db_session, request, settings, FixedBackend()).results == []


def test_embedding_recovery_reuses_chunk_ids_and_preserves_keyword_index(db_session):
    version = add_document(db_session)
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    db_session.delete(db_session.get(ChunkSearchIndex, chunk.id))
    db_session.flush()

    class DisconnectedBackend(FixedBackend):
        def embed(self, texts, kind="passage"):
            raise EmbeddingUnavailable("ai_unavailable")

    failed = embed_version(db_session, version.id, DisconnectedBackend())
    db_session.commit()
    assert failed.embedding_error == "ai_unavailable" and failed.embedded_count == 0
    keyword = search_chunks(
        db_session,
        SearchRequest(query="backup", mode="keyword"),
        Settings(_env_file=None),
        None,
    )
    assert keyword.results[0].chunk_id == chunk.id
    assert read_evidence(db_session, chunk.id).version_id == version.id

    recovered = embed_version(db_session, version.id, FixedBackend())
    db_session.commit()
    assert recovered.embedding_error is None and recovered.embedded_count == 1
    semantic = search_chunks(
        db_session,
        SearchRequest(query="restore information", mode="semantic"),
        Settings(_env_file=None),
        FixedBackend(),
    )
    assert not semantic.degraded
    assert semantic.results[0].chunk_id == chunk.id
    assert db_session.get(FileRecord, "document").current_version_id == version.id
