"""Physical page metadata must describe verified current PDF bytes only."""

from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError

from services.common.config import Settings
from services.common.models import AuthorizedRoot, FileRecord, SourceChunk
from services.scan import handler as scan_handler
from services.search import page_metadata
from services.search.embeddings import EmbeddingUnavailable
from services.search.indexing import embed_version, index_document
from services.search.page_metadata import (
    PAGE_METADATA_POLICY,
    VersionPageMetadata,
    load_page_metadata,
    metadata_matches_version,
    page_metadata_available,
    prepare_version_page_metadata,
)
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex, prepare_search_schema


def source(db, tmp_path, monkeypatch, *, pages=4, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    content = output.getvalue()
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(content)
    version = index_document(
        db, file_id="source", name=pdf.name, path=pdf.name,
        sha256=hashlib.sha256(content).hexdigest(),
        chunks=[
            {"text": "First evidence passage", "page_number": 1},
            {"text": "Second passage on the same physical page", "page_number": 1},
        ],
    )
    version.byte_size = len(content)
    version.parser_revision = "parsing-v1"
    db.flush()
    monkeypatch.setattr(scan_handler, "get_settings", lambda: Settings(
        _env_file=None, source_mounts={"search-fixtures": str(tmp_path)},
    ))
    return version, pdf


def test_counts_blank_tail_and_multiple_chunks_without_changing_canonical_rows(
    db_session, tmp_path, monkeypatch,
):
    db = db_session
    version, pdf = source(db, tmp_path, monkeypatch)
    before_pdf = pdf.read_bytes()
    chunks_before = [(c.id, c.page_number, c.text) for c in db.scalars(select(SourceChunk))]
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("metadata must not commit"))
    result = prepare_version_page_metadata(db, version.id)
    assert result.page_count == 4 and result.error is None
    assert load_page_metadata(db, version) == (4, "ready")
    assert page_metadata_available(db)
    assert pdf.read_bytes() == before_pdf
    assert [(c.id, c.page_number, c.text) for c in db.scalars(select(SourceChunk))] == chunks_before
    metadata = db.get(VersionPageMetadata, version.id)
    assert metadata_matches_version(metadata, version)
    assert metadata.policy_revision == PAGE_METADATA_POLICY
    assert metadata.byte_size == len(before_pdf)


@pytest.mark.parametrize("status,allowed", [("active", True), ("paused", True),
                                           ("revoked", False), ("revoking", False)])
def test_root_scope_checked_before_any_pdf_read(db_session, tmp_path, monkeypatch, status, allowed):
    version, _ = source(db_session, tmp_path, monkeypatch)
    root = db_session.scalar(select(AuthorizedRoot))
    root.status = status
    db_session.flush()
    if not allowed:
        monkeypatch.setattr(page_metadata, "file_identity", lambda path: pytest.fail("read denied"))
    result = prepare_version_page_metadata(db_session, version.id)
    assert (result.error is None) == allowed
    if not allowed:
        assert result.error == "page_metadata_root_not_authorized"
        assert db_session.get(VersionPageMetadata, version.id) is None


@pytest.mark.parametrize("change,error", [
    ("current", "page_metadata_version_superseded"),
    ("presence", "page_metadata_file_missing"),
    ("state", "page_metadata_version_not_ready"),
])
def test_unreadable_canonical_versions_refused_before_file_access(
    db_session, tmp_path, monkeypatch, change, error,
):
    version, _ = source(db_session, tmp_path, monkeypatch)
    record = db_session.get(FileRecord, version.file_id)
    if change == "current":
        record.current_version_id = "another-version"
    elif change == "presence":
        record.presence_status = "missing"
    else:
        version.status = "extracting"
    monkeypatch.setattr(page_metadata, "file_identity", lambda path: pytest.fail("read denied"))
    assert prepare_version_page_metadata(db_session, version.id).error == error
    assert db_session.get(VersionPageMetadata, version.id) is None


def test_preparation_refuses_bytes_changed_before_or_during_parse(
    db_session, tmp_path, monkeypatch,
):
    version, pdf = source(db_session, tmp_path, monkeypatch)
    pdf.write_bytes(pdf.read_bytes() + b"\nchanged")
    result = prepare_version_page_metadata(db_session, version.id)
    assert result.error == "page_metadata_source_changed"
    assert db_session.get(VersionPageMetadata, version.id) is None
    identities = iter([(version.content_sha256, version.byte_size), ("f" * 64, version.byte_size)])
    monkeypatch.setattr(page_metadata, "file_identity", lambda path: next(identities))
    result = prepare_version_page_metadata(db_session, version.id)
    assert result.error == "page_metadata_source_changed"
    assert db_session.get(VersionPageMetadata, version.id) is None


def test_encrypted_source_cannot_publish_page_metadata(db_session, tmp_path, monkeypatch):
    version, _ = source(db_session, tmp_path, monkeypatch, encrypted=True)
    assert prepare_version_page_metadata(db_session, version.id).error == "page_metadata_encrypted"
    assert db_session.get(VersionPageMetadata, version.id) is None


@pytest.mark.parametrize("field,value", [
    ("content_sha256", "d" * 64), ("byte_size", 0), ("parser_revision", "new-parser"),
    ("policy_revision", "unknown-policy"), ("page_count", None),
])
def test_metadata_version_identity_invalidates_stale_values(
    db_session, tmp_path, monkeypatch, field, value,
):
    version, _ = source(db_session, tmp_path, monkeypatch)
    prepare_version_page_metadata(db_session, version.id)
    metadata = db_session.get(VersionPageMetadata, version.id)
    setattr(metadata, field, value)
    # In-memory malformed values are rejected without relying on DB constraints.
    assert not metadata_matches_version(metadata, version)
    assert load_page_metadata(db_session, version) == (None, "page_metadata_stale")
    db_session.rollback()


def test_reads_missing_schema_never_create_storage(db_session, tmp_path, monkeypatch):
    version, _ = source(db_session, tmp_path, monkeypatch)
    db_session.commit()
    VersionPageMetadata.__table__.drop(bind=db_session.get_bind())
    before = set(inspect(db_session.get_bind()).get_table_names())
    assert load_page_metadata(db_session, version) == (None, "page_metadata_schema_missing")
    result = prepare_version_page_metadata(db_session, version.id)
    assert result.error == "page_metadata_schema_missing"
    assert set(inspect(db_session.get_bind()).get_table_names()) == before
    prepare_search_schema(db_session.get_bind())
    assert load_page_metadata(db_session, version) == (None, "page_metadata_missing")


def test_path_escape_and_missing_mount_are_safe_preparation_errors(
    db_session, tmp_path, monkeypatch,
):
    version, _ = source(db_session, tmp_path, monkeypatch)
    record = db_session.get(FileRecord, version.file_id)
    record.relative_path = "../outside.pdf"
    result = prepare_version_page_metadata(db_session, version.id)
    assert result.error == "page_metadata_path_unavailable"
    record.relative_path = "sample.pdf"
    monkeypatch.setattr(scan_handler, "get_settings", lambda: Settings(
        _env_file=None, source_mounts={},
    ))
    result = prepare_version_page_metadata(db_session, version.id)
    assert result.error == "page_metadata_mount_unavailable"


def test_metadata_sql_failures_are_not_reported_as_file_errors(db_session, tmp_path, monkeypatch):
    version, _ = source(db_session, tmp_path, monkeypatch)

    def fail_flush(*args, **kwargs):
        raise SQLAlchemyError("database write failed")

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(SQLAlchemyError):
        prepare_version_page_metadata(db_session, version.id)


class FixedBackend:
    model_id, dimensions = MODEL_ID, TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]


def test_metadata_failure_does_not_block_embeddings_or_keyword_evidence(
    db_session, tmp_path, monkeypatch,
):
    version, pdf = source(db_session, tmp_path, monkeypatch)
    pdf.unlink()
    result = embed_version(db_session, version.id, FixedBackend())
    assert result.embedded_count == 2 and result.embedding_error is None
    assert result.page_count is None
    assert result.page_metadata_error == "page_metadata_source_unavailable"
    assert len(list(db_session.scalars(select(ChunkTokenIndex)))) == 2
    assert len(list(db_session.scalars(select(SourceChunk)))) == 2


def test_disabled_ai_still_prepares_real_pdf_page_metadata(db_session, tmp_path, monkeypatch):
    version, _ = source(db_session, tmp_path, monkeypatch)

    class DisabledBackend(FixedBackend):
        def embed(self, texts, kind="passage"):
            raise EmbeddingUnavailable("ai_disabled")

    result = embed_version(db_session, version.id, DisabledBackend())
    assert result.embedding_error == "ai_disabled" and result.embedded_count == 0
    assert result.page_count == 4 and result.page_metadata_error is None
    assert load_page_metadata(db_session, version) == (4, "ready")
