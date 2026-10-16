from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    SourceChunk,
    SourceFile,
    SourceFileStatus,
    SourceVersion,
    SourceVersionStatus,
)
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    validate_vectors,
)
from services.search.text import DIMENSIONS, MAX_BATCH_SIZE, MAX_TEXT_CHARS, MODEL_ID


@dataclass(frozen=True)
class IndexResult:
    version_id: str
    chunk_count: int
    embedded_count: int
    embedding_error: str | None = None


def embed_version(db: Session, version_id: str, backend: EmbeddingBackend) -> IndexResult:
    """C's worker handler: bounded batches, all-or-nothing vector publication.

    Text is already persisted by B. A owns scheduling/commit; this function never
    commits. Failed embedding leaves text and existing vectors intact.
    """
    version = db.get(SourceVersion, version_id)
    if version is None:
        raise ValueError("source version not found")
    chunks = list(
        db.scalars(
            select(SourceChunk)
            .where(SourceChunk.source_version_id == version_id)
            .order_by(SourceChunk.chunk_index)
        )
    )
    if not chunks:
        return IndexResult(version_id, 0, 0, "no_chunks")
    if backend.model_id != MODEL_ID or backend.dimensions != DIMENSIONS:
        return IndexResult(version_id, len(chunks), 0, "embedding_model_mismatch")
    vectors: list[list[float]] = []
    try:
        for offset in range(0, len(chunks), MAX_BATCH_SIZE):
            texts = [
                chunk.text[:MAX_TEXT_CHARS] for chunk in chunks[offset : offset + MAX_BATCH_SIZE]
            ]
            vectors.extend(validate_vectors(backend.embed(texts, "passage"), len(texts)))
    except EmbeddingUnavailable as exc:
        return IndexResult(version_id, len(chunks), 0, str(exc))
    # No database writes before every batch has succeeded.
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = MODEL_ID
        chunk.embedding_dimensions = DIMENSIONS
    version.embedding_model = MODEL_ID
    version.embedding_dimensions = DIMENSIONS
    db.flush()
    return IndexResult(version_id, len(chunks), len(vectors))


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
) -> SourceVersion:
    """Fixture/import adapter until A/B's scanner/parser contract is merged.

    An existing version is immutable. Identical re-import returns it; changed text
    needs a new version number. File identity is supplied by the scanner/caller.
    Embeddings are optional: missing AI must never discard the basic text.
    """
    if not name.strip() or not path.strip() or not file_id.strip() or len(file_id) > 36:
        raise ValueError("file identity, name and path are required")
    if version_number < 1:
        raise ValueError("version_number must be positive")
    items: list[dict] = []
    for position, item in enumerate(chunks):
        text_value = item.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise ValueError(f"chunk {position} must contain text")
        index = int(item.get("chunk_index", position))
        page_start = int(item.get("page_start", 1))
        page_end = int(item.get("page_end", page_start))
        if index < 0 or page_start < 1 or page_end < page_start:
            raise ValueError(f"invalid source location for chunk {position}")
        items.append(
            {
                "chunk_index": index,
                "text": text_value,
                "page_start": page_start,
                "page_end": page_end,
            }
        )
    if not items or len({item["chunk_index"] for item in items}) != len(items):
        raise ValueError("non-empty chunks with unique chunk_index are required")
    items.sort(key=lambda item: item["chunk_index"])
    fingerprint = hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if sha256 is not None and (
        len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)
    ):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    source_hash = sha256 or fingerprint

    existing = db.scalar(
        select(SourceVersion).where(
            SourceVersion.source_file_id == file_id,
            SourceVersion.version_number == version_number,
        )
    )
    if existing is not None:
        current_items = [
            {
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
            }
            for chunk in existing.chunks
        ]
        if current_items != items or existing.sha256 != source_hash:
            raise ValueError("source version is immutable; use a new version_number")
        return existing

    # The scanner owns file identities; row locking serializes updates on PostgreSQL.
    source_file = db.scalar(select(SourceFile).where(SourceFile.id == file_id).with_for_update())
    if source_file is None:
        source_file = SourceFile(
            id=file_id,
            name=name.strip(),
            path=path.strip(),
            sha256=source_hash,
            mime_type=mime_type,
            status=SourceFileStatus.READY.value,
        )
        db.add(source_file)
        db.flush()
    current = db.scalar(
        select(SourceVersion).where(
            SourceVersion.source_file_id == file_id,
            SourceVersion.is_current.is_(True),
        )
    )
    is_current = current is None or version_number > current.version_number
    if is_current:
        if current is not None:
            current.is_current = False
            db.flush()  # Clear the partial unique index before publishing the new version.
        source_file.sha256 = source_hash
        source_file.name = name.strip()
        source_file.path = path.strip()
        source_file.mime_type = mime_type
        source_file.status = SourceFileStatus.READY.value
    version = SourceVersion(
        id=version_id or str(uuid.uuid4()),
        source_file_id=file_id,
        version_number=version_number,
        sha256=source_hash,
        page_count=max(item["page_end"] for item in items),
        status=SourceVersionStatus.READY.value,
        is_current=is_current,
    )
    version.chunks = [SourceChunk(**item) for item in items]
    db.add(version)
    db.flush()
    if backend is not None:
        embed_version(db, version.id, backend)
    if commit:
        db.commit()
    return version
