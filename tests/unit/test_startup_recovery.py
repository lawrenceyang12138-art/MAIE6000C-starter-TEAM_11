"""Model startup recovery reuses the normal, authorized version-job pipeline."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    Job,
    SourceChunk,
)
from services.search.indexing import index_document
from services.search.startup_recovery import queue_startup_embeddings
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex
from tests.support.search import materialize_search_source


class FixedBackend:
    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]


def document(db, name="one", *, backend=None, text="Database recovery source text"):
    version = index_document(
        db, file_id=name, name="same-name.pdf", path=f"{name}/same-name.pdf",
        chunks=[{"text": text, "page_number": 1}], backend=backend,
    )
    path = materialize_search_source(db, version)
    return version, path


def jobs(db):
    return list(db.scalars(select(Job).where(Job.job_type == "embed_file")))


def test_missing_vectors_queue_once_and_caller_owns_commit(db_session):
    version, path = document(db_session)
    original = path.read_bytes()
    db_session.commit()
    assert queue_startup_embeddings(db_session) == 1
    assert queue_startup_embeddings(db_session) == 0
    assert len(jobs(db_session)) == 1
    job = jobs(db_session)[0]
    assert (job.version_id, job.status, job.attempts) == (version.id, "pending", 0)
    assert path.read_bytes() == original
    assert db_session.get(FileRecord, version.file_id).current_version_id == version.id
    db_session.expunge(job)
    db_session.rollback()
    assert jobs(db_session) == []
    assert queue_startup_embeddings(db_session) == 1


def test_compatible_vectors_are_not_regenerated(db_session):
    version, _ = document(db_session, backend=FixedBackend())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    token_index = db_session.get(ChunkTokenIndex, chunk.id)
    original_vectors = token_index.token_vectors
    assert queue_startup_embeddings(db_session) == 0
    assert token_index.token_vectors == original_vectors
    assert not jobs(db_session)


@pytest.mark.parametrize("fault", ["missing", "revision", "dimensions", "text", "matrix"])
def test_incompatible_vectors_queue_recovery_without_deleting_old_vectors(db_session, fault):
    version, _ = document(db_session, backend=FixedBackend())
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    index = db_session.get(ChunkTokenIndex, chunk.id)
    if fault == "missing":
        db_session.delete(index)
    elif fault == "revision":
        index.model_revision = "retired-revision"
    elif fault == "dimensions":
        index.token_dimensions = 384
    elif fault == "text":
        index.text_sha256 = "0" * 64
    else:
        index.token_vectors = [[0.0] * TOKEN_DIMENSIONS]
    db_session.flush()
    assert queue_startup_embeddings(db_session) == 1
    assert len(jobs(db_session)) == 1
    if fault != "missing":
        assert db_session.get(ChunkTokenIndex, chunk.id) is index


@pytest.mark.parametrize("state", ["pending", "claimed"])
def test_existing_live_embed_job_prevents_duplicates(db_session, state):
    version, _ = document(db_session)
    db_session.add(Job(job_type="embed_file", version_id=version.id, status=state))
    assert queue_startup_embeddings(db_session) == 0
    assert len(jobs(db_session)) == 1


@pytest.mark.parametrize("state", ["completed", "failed"])
def test_terminal_embedding_job_does_not_block_new_model_recovery(db_session, state):
    version, _ = document(db_session)
    db_session.add(Job(job_type="embed_file", version_id=version.id, status=state, attempts=2))
    assert queue_startup_embeddings(db_session) == 1
    assert len(jobs(db_session)) == 2
    assert jobs(db_session)[0].attempts == 2


@pytest.mark.parametrize("target,state", [
    ("root", "paused"), ("root", "revoking"), ("root", "revoked"),
    ("file", "missing"), ("file", "unavailable"),
    ("version", "discovered"), ("version", "extracting"), ("version", "failed"),
    ("version", "unsupported"),
])
def test_recovery_obeys_authorization_presence_and_version_scope(db_session, target, state):
    version, _ = document(db_session)
    record = db_session.get(FileRecord, version.file_id)
    if target == "root":
        db_session.get(AuthorizedRoot, record.root_id).status = state
    elif target == "file":
        record.presence_status = state
    else:
        version.status = state
    assert queue_startup_embeddings(db_session) == 0
    assert not jobs(db_session)


@pytest.mark.parametrize("state", ["basic_ready", "enriched"])
def test_both_parsed_states_can_have_missing_vectors(db_session, state):
    version, _ = document(db_session)
    version.status = state
    assert queue_startup_embeddings(db_session) == 1


def test_only_current_version_is_recovered_and_source_identity_is_unchanged(db_session):
    old, _ = document(db_session, text="old content")
    current, path = document(db_session, text="current content")
    assert old.id != current.id
    original = path.read_bytes()
    assert queue_startup_embeddings(db_session) == 1
    assert [job.version_id for job in jobs(db_session)] == [current.id]
    assert path.read_bytes() == original


@pytest.mark.parametrize("fault", ["missing", "changed", "no_current", "unconfigured_mount"])
def test_database_presence_alone_is_not_enough_to_enqueue(db_session, monkeypatch, fault):
    version, path = document(db_session)
    record = db_session.get(FileRecord, version.file_id)
    if fault == "missing":
        path.unlink()
    elif fault == "changed":
        path.write_bytes(b"different source bytes not rescanned")
    elif fault == "no_current":
        record.current_version_id = None
    else:
        db_session.get(AuthorizedRoot, record.root_id).mount_id = "unknown-mount"
    assert queue_startup_embeddings(db_session) == 0
    assert not jobs(db_session)


def test_no_chunks_and_missing_token_schema_are_not_queued(db_session, monkeypatch):
    version, _ = document(db_session)
    chunk = db_session.scalar(select(SourceChunk).where(SourceChunk.version_id == version.id))
    db_session.delete(chunk)
    assert queue_startup_embeddings(db_session) == 0
    from services.search import startup_recovery

    monkeypatch.setattr(startup_recovery, "token_index_available", lambda db: False)
    assert queue_startup_embeddings(db_session) == 0
    assert not jobs(db_session)


def test_same_name_at_different_paths_keeps_two_version_targets(db_session):
    one, _ = document(db_session, name="one")
    two, _ = document(db_session, name="two")
    assert queue_startup_embeddings(db_session) == 2
    assert {job.version_id for job in jobs(db_session)} == {one.id, two.id}
