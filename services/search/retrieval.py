from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
    VersionStatus,
)
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    cosine_similarity,
    validate_vectors,
)
from services.search.text import (
    DIMENSIONS,
    MODEL_ID,
    normalize_text,
    search_terms,
    tokenize,
)


@dataclass(frozen=True)
class SearchHit:
    root_id: str
    file_id: str
    file_name: str
    file_path: str
    version_id: str
    version_created_at: datetime
    chunk_id: str
    ordinal: int
    page: int | None
    text: str
    reason: str
    score: float
    keyword_score: float
    semantic_score: float


@dataclass(frozen=True)
class SearchResultSet:
    results: list[SearchHit]
    total: int
    effective_mode: str
    degraded: bool
    degradation_reason: str | None
    embedding_model: str | None
    embedding_dimensions: int | None
    candidate_count: int
    candidate_limit: int


def _eligible_rows(
    db: Session,
    root_id: str | None,
    file_id: str | None,
):
    statement = (
        select(
            SourceChunk,
            FileVersion,
            FileRecord,
            AuthorizedRoot,
            ChunkSearchIndex,
        )
        .join(FileVersion, SourceChunk.version_id == FileVersion.id)
        .join(FileRecord, FileVersion.file_id == FileRecord.id)
        .join(AuthorizedRoot, FileRecord.root_id == AuthorizedRoot.id)
        .outerjoin(ChunkSearchIndex, ChunkSearchIndex.chunk_id == SourceChunk.id)
        .where(FileRecord.current_version_id == FileVersion.id)
        .where(
            FileVersion.status.in_(
                [VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value]
            )
        )
        .where(FileRecord.presence_status == FilePresence.PRESENT.value)
        .where(
            AuthorizedRoot.status.in_(
                [RootStatus.ACTIVE.value, RootStatus.PAUSED.value]
            )
        )
    )
    if root_id is not None:
        statement = statement.where(FileRecord.root_id == root_id)
    if file_id is not None:
        statement = statement.where(FileRecord.id == file_id)
    return list(db.execute(statement).all())


def _terms_for(row: tuple) -> str:
    chunk, _version, _file_record, _root, index = row
    return index.search_terms if index is not None else search_terms(chunk.text)


def _text_for(row: tuple) -> str:
    chunk, _version, _file_record, _root, index = row
    return index.search_text if index is not None else normalize_text(chunk.text)


def _keyword_score(
    row: tuple,
    terms: tuple[str, ...],
    normalized_query: str,
) -> tuple[float, list[str]]:
    chunk, _version, file_record, _root, _index = row
    stored_terms = _terms_for(row)
    stored_text = _text_for(row)
    matched = [term for term in terms if f" {term} " in stored_terms]
    coverage = len(matched) / len(terms) if terms else 0.0
    phrase = bool(terms) and normalized_query in stored_text
    name_match = normalized_query in normalize_text(file_record.name)
    score = min(1.0, coverage * 0.8 + (0.2 if phrase else 0.0) + (0.25 if name_match else 0.0))
    reasons: list[str] = []
    if matched:
        reasons.append("keyword: " + ", ".join(matched[:8]))
    if phrase:
        reasons.append("phrase match")
    if name_match:
        reasons.append("file name match")
    return score, reasons


def _keyword_candidates(
    rows: list[tuple],
    terms: tuple[str, ...],
    normalized_query: str,
) -> dict[str, tuple[tuple, float, list[str]]]:
    candidates: dict[str, tuple[tuple, float, list[str]]] = {}
    for row in rows:
        chunk, _version, _file_record, _root, _index = row
        score, reasons = _keyword_score(row, terms, normalized_query)
        if score <= 0:
            continue
        candidates[chunk.id] = (row, score, reasons)
    return candidates


def _semantic_score(row: tuple, vector: list[float]) -> float:
    chunk, version, _file_record, _root, index = row
    if (
        index is None
        or index.embedding is None
        or index.embedding_model != MODEL_ID
        or index.embedding_dimensions != DIMENSIONS
        or version.status not in {VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value}
    ):
        return 0.0
    return max(0.0, cosine_similarity(vector, list(index.embedding)))


def search_chunks(
    db: Session,
    *,
    query: str,
    mode: str,
    top_k: int,
    root_id: str | None,
    file_id: str | None,
    settings: Settings,
    backend: EmbeddingBackend | None,
) -> SearchResultSet:
    """Search canonical current chunks and return file-deduplicated evidence.

    Keyword results are always available over the derived index. Semantic and
    hybrid modes use pinned vectors when present and report an explicit
    degradation otherwise; a missing model never hides keyword evidence.
    """
    normalized_query = normalize_text(query)
    terms = tokenize(query)
    rows = _eligible_rows(db, root_id, file_id)
    keyword_candidates = _keyword_candidates(rows, terms, normalized_query)

    effective_mode = mode
    degradation: str | None = None
    vector: list[float] | None = None
    semantic_candidates: dict[str, tuple[tuple, float]] = {}

    if mode in {"semantic", "hybrid"}:
        if not settings.embedding_enabled:
            degradation = "ai_disabled"
        elif backend is None:
            degradation = "ai_unavailable"
        else:
            try:
                if backend.model_id != MODEL_ID or backend.dimensions != DIMENSIONS:
                    raise EmbeddingUnavailable("embedding_model_mismatch")
                vector = validate_vectors(backend.embed([query], "query"), 1)[0]
                for row in rows:
                    score = _semantic_score(row, vector)
                    if score <= 0:
                        continue
                    chunk, _version, _file_record, _root, _index = row
                    semantic_candidates[chunk.id] = (row, score)
                if not semantic_candidates:
                    degradation = "embeddings_not_ready"
            except EmbeddingUnavailable as exc:
                degradation = str(exc)

        if degradation and not semantic_candidates:
            effective_mode = "keyword"
        else:
            complete = sum(
                1
                for row in rows
                if row[4] is not None
                and row[4].embedding is not None
                and row[4].embedding_model == MODEL_ID
                and row[4].embedding_dimensions == DIMENSIONS
            )
            if semantic_candidates and complete < len(rows):
                degradation = "partial_embeddings"

    candidate_ids: set[str]
    if effective_mode == "keyword":
        candidate_ids = set(keyword_candidates)
    elif effective_mode == "semantic":
        candidate_ids = set(semantic_candidates)
    else:
        candidate_ids = set(keyword_candidates) | set(semantic_candidates)

    hits: list[SearchHit] = []
    best_by_file: dict[str, SearchHit] = {}
    for chunk_id in candidate_ids:
        keyword_entry = keyword_candidates.get(chunk_id)
        semantic_entry = semantic_candidates.get(chunk_id)
        row = (keyword_entry or semantic_entry)[0]
        chunk, version, file_record, root, _index = row
        keyword_score = keyword_entry[1] if keyword_entry is not None else 0.0
        keyword_reasons = keyword_entry[2] if keyword_entry is not None else []
        semantic_score = semantic_entry[1] if semantic_entry is not None else 0.0

        if effective_mode == "keyword":
            score = keyword_score
        elif effective_mode == "semantic":
            score = semantic_score
        else:
            weight_sum = settings.search_keyword_weight + settings.search_semantic_weight
            score = (
                keyword_score * settings.search_keyword_weight
                + semantic_score * settings.search_semantic_weight
            ) / weight_sum
        if score <= 0:
            continue

        reason_parts = list(keyword_reasons)
        if semantic_score > 0 and effective_mode != "keyword":
            reason_parts.append(f"semantic cosine: {semantic_score:.4f}")
        hit = SearchHit(
            root_id=root.id,
            file_id=file_record.id,
            file_name=file_record.name,
            file_path=file_record.relative_path,
            version_id=version.id,
            version_created_at=version.created_at,
            chunk_id=chunk.id,
            ordinal=chunk.ordinal,
            page=chunk.page_number,
            text=chunk.text[:2000],
            reason="; ".join(reason_parts),
            score=round(min(score, 1.0), 6),
            keyword_score=round(keyword_score, 6),
            semantic_score=round(semantic_score, 6),
        )
        current = best_by_file.get(file_record.id)
        if current is None or (hit.score, -hit.ordinal) > (current.score, -current.ordinal):
            best_by_file[file_record.id] = hit

    hits = list(best_by_file.values())
    hits.sort(key=lambda hit: (-hit.score, hit.file_name.casefold(), hit.ordinal, hit.chunk_id))
    return SearchResultSet(
        results=hits[:top_k],
        total=len(hits),
        effective_mode=effective_mode,
        degraded=degradation is not None,
        degradation_reason=degradation,
        embedding_model=MODEL_ID if effective_mode != "keyword" else None,
        embedding_dimensions=DIMENSIONS if effective_mode != "keyword" else None,
        candidate_count=len(rows),
        candidate_limit=settings.search_max_candidates,
    )
