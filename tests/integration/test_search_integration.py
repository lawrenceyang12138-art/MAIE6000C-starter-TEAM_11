from __future__ import annotations

from sqlalchemy import select

from services.api.app.integration_routes import get_embedding_backend
from services.common.models import (
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    SourceChunk,
    VersionStatus,
)
from services.parsing.chunking import Chunk
from services.parsing.persist import persist_chunks
from services.search.indexing import embed_version
from services.search.text import DIMENSIONS, MODEL_ID


class FixedEmbedding:
    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]


def _ready_version(db_session, make_file_version, text: str) -> tuple[str, str]:
    version_id = make_file_version(sha256="d" * 64)
    version = db_session.get(FileVersion, version_id)
    version.status = VersionStatus.BASIC_READY.value
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.current_version_id = version_id
    db_session.commit()
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text=text)],
    )
    return version_id, file_record.id


def test_keyword_index_is_created_and_rebuilt_with_chunk_text(
    client, db_session, make_file_version
):
    version_id, file_id = _ready_version(db_session, make_file_version, "Alpha recovery notes")
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version_id))
    index_row = db_session.get(ChunkSearchIndex, chunk.id)
    assert index_row is not None
    assert "alpha" in index_row.search_terms

    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="Beta replacement notes")],
    )
    db_session.expire_all()
    old = client.post("/search", json={"query": "alpha", "mode": "keyword"})
    new = client.post("/search", json={"query": "beta", "mode": "keyword"})
    assert old.json()["total"] == 0
    assert new.json()["total"] == 1
    assert new.json()["results"][0]["file_id"] == file_id


def test_semantic_search_uses_the_canonical_chunk_index(
    client, db_session, make_file_version
):
    version_id, file_id = _ready_version(
        db_session,
        make_file_version,
        "A passage with no useful query words",
    )
    result = embed_version(db_session, version_id, FixedEmbedding())
    assert result.embedded_count == 1
    db_session.commit()

    app_dependency = get_embedding_backend
    from services.api.app.main import app

    app.dependency_overrides[app_dependency] = FixedEmbedding
    try:
        response = client.post(
            "/search",
            json={"query": "completely different wording", "mode": "semantic"},
        )
    finally:
        app.dependency_overrides.pop(app_dependency, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_mode"] == "semantic"
    assert payload["degraded"] is False
    assert payload["results"][0]["file_id"] == file_id
    assert payload["results"][0]["semantic_score"] == 1.0
