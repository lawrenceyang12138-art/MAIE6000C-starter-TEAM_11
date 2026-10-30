from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
    VersionStatus,
)
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    validate_vectors,
)
from services.search.page_metadata import prepare_version_page_metadata
from services.search.text import (
    MAX_BATCH_SIZE, MAX_TEXT_CHARS, MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS,
)
from services.search.token_store import ChunkTokenIndex, text_fingerprint, token_index_available


@dataclass(frozen=True)
class IndexResult:
    version_id: str
    chunk_count: int
    embedded_count: int
    embedding_error: str | None = None
    page_count: int | None = None
    page_metadata_error: str | None = None


def embed_version(db: Session, version_id: str, backend: EmbeddingBackend) -> IndexResult:
    """Publish native token matrices atomically after every document batch passes."""
    version = db.get(FileVersion, version_id)
    if version is None:
        raise ValueError("file version not found")
    metadata = prepare_version_page_metadata(db, version_id)

    def result(chunk_count: int, embedded_count: int, error: str | None = None) -> IndexResult:
        return IndexResult(
            version_id, chunk_count, embedded_count, error,
            metadata.page_count, metadata.error,
        )

    chunks = list(
        db.scalars(
            select(SourceChunk)
            .where(SourceChunk.version_id == version_id)
            .order_by(SourceChunk.ordinal)
        )
    )
    if not chunks:
        return result(0, 0, "no_chunks")

    indexes: list[ChunkSearchIndex] = []
    for chunk in chunks:
        index = db.get(ChunkSearchIndex, chunk.id)
        if index is None:
            index = ChunkSearchIndex(chunk_id=chunk.id, search_text=chunk.text)
            db.add(index)
        # The retired dense model must never survive as an implicit fallback.
        index.embedding = None
        index.embedding_model = None
        index.embedding_dimensions = None
        indexes.append(index)
    db.flush()

    if backend.model_id != MODEL_ID or backend.dimensions != TOKEN_DIMENSIONS:
        return result(len(chunks), 0, "embedding_model_mismatch")
    if not token_index_available(db):
        return result(len(chunks), 0, "token_index_schema_missing")
    vectors: list[list[list[float]]] = []
    try:
        for offset in range(0, len(chunks), MAX_BATCH_SIZE):
            texts = [
                chunk.text[:MAX_TEXT_CHARS]
                for chunk in chunks[offset : offset + MAX_BATCH_SIZE]
            ]
            vectors.extend(validate_vectors(backend.embed(texts, "passage"), len(texts)))
    except EmbeddingUnavailable as exc:
        return result(len(chunks), 0, str(exc))

    for chunk, vector in zip(chunks, vectors, strict=True):
        token_index = db.get(ChunkTokenIndex, chunk.id)
        if token_index is None:
            token_index = ChunkTokenIndex(chunk_id=chunk.id)
            db.add(token_index)
        token_index.model_id = MODEL_ID
        token_index.model_revision = MODEL_REVISION
        token_index.token_dimensions = TOKEN_DIMENSIONS
        token_index.token_count = len(vector)
        token_index.token_vectors = vector
        token_index.text_sha256 = text_fingerprint(chunk.text)
    db.flush()
    return result(len(chunks), len(vectors))


def index_document(
    db: Session,
    *,
    name: str,
    path: str,
    chunks: Iterable[Mapping[str, object]],
    file_id: str,
    version_number: int = 1,
    version_id: str | None = None,
    sha256: str | None = None,
    mime_type: str = "application/pdf",
    backend: EmbeddingBackend | None = None,
    commit: bool = False,
) -> FileVersion:
    """Import search fixtures through the canonical root/file/version/chunk tables.

    Legacy version and page-range inputs are mapped to a current-version pointer,
    one-based ordinal and a single canonical page number.
    """
    del mime_type
    if not name.strip() or not path.strip() or not file_id.strip() or len(file_id) > 36:
        raise ValueError("file identity, name and path are required")
    if version_number < 1:
        raise ValueError("version_number must be positive")

    items: list[dict[str, object]] = []
    for position, item in enumerate(chunks):
        text_value = item.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise ValueError(f"chunk {position} must contain text")
        old_index = int(item.get("chunk_index", position))
        page = int(item.get("page_number", item.get("page_start", 1)))
        page_end = int(item.get("page_end", page))
        if old_index < 0 or page < 1 or page_end < page:
            raise ValueError(f"invalid source location for chunk {position}")
        items.append({"ordinal": old_index + 1, "text": text_value, "page_number": page})
    if not items or len({item["ordinal"] for item in items}) != len(items):
        raise ValueError("non-empty chunks with unique chunk_index are required")
    items.sort(key=lambda item: int(item["ordinal"]))

    fingerprint = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if sha256 is not None and (
        len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)
    ):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    content_hash = sha256 or fingerprint

    root = db.scalar(
        select(AuthorizedRoot).where(
            AuthorizedRoot.mount_id == "search-fixtures",
            AuthorizedRoot.relative_path == ".",
        )
    )
    if root is None:
        root = AuthorizedRoot(
            mount_id="search-fixtures",
            relative_path=".",
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        db.flush()

    source_file = db.get(FileRecord, file_id)
    if source_file is None:
        source_file = FileRecord(
            id=file_id,
            root_id=root.id,
            relative_path=path.strip().replace("\\", "/"),
            name=name.strip(),
        )
        db.add(source_file)
        db.flush()
    else:
        source_file.name = name.strip()
        source_file.relative_path = path.strip().replace("\\", "/")

    version = db.scalar(
        select(FileVersion).where(
            FileVersion.file_id == file_id,
            FileVersion.content_sha256 == content_hash,
        )
    )
    if version is not None:
        current_items = list(
            db.execute(
                select(SourceChunk.ordinal, SourceChunk.text, SourceChunk.page_number)
                .where(SourceChunk.version_id == version.id)
                .order_by(SourceChunk.ordinal)
            )
        )
        expected = [
            (item["ordinal"], item["text"], item["page_number"])
            for item in items
        ]
        if current_items != expected:
            raise ValueError("file version is immutable; changed content needs a new hash")
        if backend is not None:
            embed_version(db, version.id, backend)
        if commit:
            db.commit()
        return version

    version = FileVersion(
        id=version_id or str(uuid.uuid4()),
        file_id=file_id,
        content_sha256=content_hash,
        byte_size=sum(len(str(item["text"]).encode("utf-8")) for item in items),
        status=VersionStatus.BASIC_READY.value,
    )
    db.add(version)
    db.flush()
    chunks_to_add = [
        SourceChunk(
            id=str(uuid.uuid4()),
            version_id=version.id,
            ordinal=int(item["ordinal"]),
            page_number=int(item["page_number"]),
            text=str(item["text"]),
        )
        for item in items
    ]
    db.add_all(chunks_to_add)
    db.flush()
    source_file.current_version_id = version.id
    source_file.presence_status = "present"
    if backend is not None:
        embed_version(db, version.id, backend)
    else:
        db.add_all(
            [
                ChunkSearchIndex(chunk_id=chunk.id, search_text=chunk.text)
                for chunk in chunks_to_add
            ]
        )
    db.flush()
    if commit:
        db.commit()
    return version
