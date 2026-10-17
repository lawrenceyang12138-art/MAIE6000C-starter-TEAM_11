from __future__ import annotations

from collections import defaultdict

from sqlalchemy import case, exists, func, literal_column, or_, select
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
from services.common.schemas import SearchMode, SearchRequest, SearchResponse, SearchResultRead
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    cosine_similarity,
    validate_vectors,
)
from services.search.text import DIMENSIONS, MODEL_ID, normalize_text, tokenize


def _base_statement(request: SearchRequest):
    stmt = (
        select(SourceChunk, ChunkSearchIndex, FileVersion, FileRecord, AuthorizedRoot)
        .join(ChunkSearchIndex, ChunkSearchIndex.chunk_id == SourceChunk.id)
        .join(FileVersion, SourceChunk.version_id == FileVersion.id)
        .join(FileRecord, FileVersion.file_id == FileRecord.id)
        .join(AuthorizedRoot, FileRecord.root_id == AuthorizedRoot.id)
        .where(
            AuthorizedRoot.status.in_([RootStatus.ACTIVE.value, RootStatus.PAUSED.value]),
            FileRecord.presence_status == FilePresence.PRESENT.value,
            FileRecord.current_version_id == FileVersion.id,
            FileVersion.status.in_(
                [VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value]
            ),
        )
    )
    if request.root_id is not None:
        stmt = stmt.where(AuthorizedRoot.id == request.root_id)
    if request.file_id is not None:
        stmt = stmt.where(FileRecord.id == request.file_id)
    return stmt


def _bounded_candidates(db: Session, base, score, predicate, limit: int):
    """Bound candidates after selecting one best matching chunk per file."""
    ranked = (
        base.with_only_columns(
            SourceChunk.id.label("chunk_id"),
            score.label("rank_score"),
            func.row_number()
            .over(
                partition_by=FileRecord.id,
                order_by=(score.desc(), SourceChunk.ordinal, SourceChunk.id),
            )
            .label("file_rank"),
        )
        .where(predicate)
        .subquery()
    )
    ids = (
        select(ranked.c.chunk_id)
        .where(ranked.c.file_rank == 1)
        .order_by(ranked.c.rank_score.desc(), ranked.c.chunk_id)
        .limit(limit)
    )
    return list(db.execute(base.where(SourceChunk.id.in_(ids))))


def _keyword_candidates(db: Session, base, query: str, limit: int):
    terms = tokenize(query)
    if not terms:
        return []
    phrase_match = ChunkSearchIndex.search_text.contains(
        normalize_text(query), autoescape=True
    )
    name_match = func.lower(FileRecord.name).contains(normalize_text(query), autoescape=True)
    coverage = sum(
        case(
            (ChunkSearchIndex.search_terms.contains(f" {term} ", autoescape=True), 1.0),
            else_=0.0,
        )
        for term in terms
    ) / len(terms)
    score = coverage * 0.8 + case((phrase_match, 0.2), else_=0.0)
    score += case((name_match, 0.25), else_=0.0)
    if db.bind.dialect.name == "postgresql":
        document = func.to_tsvector(
            literal_column("'simple'"), ChunkSearchIndex.search_terms
        )
        ts_query = func.to_tsquery(literal_column("'simple'"), " | ".join(terms))
        predicate = or_(document.op("@@")(ts_query), name_match)
    else:
        predicate = or_(coverage > 0, name_match)
    return _bounded_candidates(db, base, score, predicate, limit)


def _semantic_candidates(db: Session, base, vector: list[float], limit: int):
    matching_model = (
        ChunkSearchIndex.embedding.is_not(None)
        & (ChunkSearchIndex.embedding_model == MODEL_ID)
        & (ChunkSearchIndex.embedding_dimensions == DIMENSIONS)
    )
    if db.bind.dialect.name == "postgresql":
        score = 1.0 - ChunkSearchIndex.embedding.cosine_distance(vector)
        return _bounded_candidates(db, base, score, matching_model, limit)
    rows = list(db.execute(base.where(matching_model)))
    rows.sort(
        key=lambda row: (
            -cosine_similarity(vector, row[1].embedding),
            row[0].ordinal,
            row[0].id,
        )
    )
    seen: set[str] = set()
    result = []
    for row in rows:
        if row[3].id not in seen:
            result.append(row)
            seen.add(row[3].id)
        if len(result) >= limit:
            break
    return result


def search_chunks(
    db: Session,
    request: SearchRequest,
    settings: Settings,
    backend: EmbeddingBackend | None,
) -> SearchResponse:
    base = _base_statement(request)
    limit = settings.search_max_candidates
    keyword_rows = _keyword_candidates(db, base, request.query, limit)
    degradation: str | None = None
    vector: list[float] | None = None
    semantic_rows = []
    effective_mode = request.mode
    if request.mode != SearchMode.KEYWORD:
        if not settings.embedding_enabled:
            degradation = "ai_disabled"
        elif backend is None:
            degradation = "ai_unavailable"
        else:
            try:
                if backend.model_id != MODEL_ID or backend.dimensions != DIMENSIONS:
                    raise EmbeddingUnavailable("embedding_model_mismatch")
                vector = validate_vectors(backend.embed([request.query], "query"), 1)[0]
                semantic_rows = _semantic_candidates(db, base, vector, limit)
                if not semantic_rows:
                    degradation = "embeddings_not_ready"
            except EmbeddingUnavailable as exc:
                degradation = str(exc)
        if degradation:
            effective_mode = SearchMode.KEYWORD

    rows_by_id = {row[0].id: row for row in keyword_rows}
    if effective_mode == SearchMode.SEMANTIC:
        rows_by_id = {row[0].id: row for row in semantic_rows}
    elif effective_mode == SearchMode.HYBRID:
        rows_by_id.update({row[0].id: row for row in semantic_rows})
    if effective_mode != SearchMode.KEYWORD:
        incomplete = base.with_only_columns(SourceChunk.id).where(
            or_(
                ChunkSearchIndex.embedding.is_(None),
                ChunkSearchIndex.embedding_model.is_(None),
                ChunkSearchIndex.embedding_model != MODEL_ID,
                ChunkSearchIndex.embedding_dimensions.is_(None),
                ChunkSearchIndex.embedding_dimensions != DIMENSIONS,
            )
        )
        if db.scalar(select(exists(incomplete))):
            degradation = "partial_embeddings"

    terms = set(tokenize(request.query))
    normalized_query = normalize_text(request.query)
    hits: list[SearchResultRead] = []
    for chunk, search_index, version, source_file, root in rows_by_id.values():
        matched = sorted(terms.intersection(tokenize(chunk.text)))
        coverage = len(matched) / len(terms) if terms else 0.0
        phrase = bool(terms) and normalized_query in search_index.search_text
        name_match = bool(terms) and normalized_query in normalize_text(source_file.name)
        lexical = min(
            1.0,
            coverage * 0.8 + (0.2 if phrase else 0) + (0.25 if name_match else 0),
        )
        semantic = 0.0
        if (
            vector is not None
            and search_index.embedding is not None
            and search_index.embedding_model == MODEL_ID
            and search_index.embedding_dimensions == DIMENSIONS
        ):
            semantic = max(
                0.0, cosine_similarity(vector, list(search_index.embedding))
            )
        if effective_mode == SearchMode.KEYWORD:
            score = lexical
        elif effective_mode == SearchMode.SEMANTIC:
            score = semantic
        else:
            weight_sum = settings.search_keyword_weight + settings.search_semantic_weight
            score = (
                lexical * settings.search_keyword_weight
                + semantic * settings.search_semantic_weight
            ) / weight_sum
        if score <= 0:
            continue
        reasons = []
        if matched:
            reasons.append("keyword: " + ", ".join(matched[:8]))
        if name_match:
            reasons.append("file name match")
        if semantic > 0 and effective_mode != SearchMode.KEYWORD:
            reasons.append(f"semantic cosine: {semantic:.4f}")
        hits.append(
            SearchResultRead(
                root_id=root.id,
                file_id=source_file.id,
                file_name=source_file.name,
                file_path=source_file.relative_path,
                version_id=version.id,
                version_created_at=version.created_at,
                chunk_id=chunk.id,
                ordinal=chunk.ordinal,
                page=chunk.page_number,
                text=chunk.text[:2000],
                reason="; ".join(reasons),
                score=round(min(score, 1.0), 6),
                keyword_score=round(lexical, 6),
                semantic_score=round(semantic, 6),
            )
        )
    hits.sort(
        key=lambda hit: (
            -hit.score,
            -hit.keyword_score,
            hit.file_id,
            hit.ordinal,
            hit.chunk_id,
        )
    )
    by_file: dict[str, list[SearchResultRead]] = defaultdict(list)
    for hit in hits:
        by_file[hit.file_id].append(hit)
    selected = [file_hits[0] for file_hits in by_file.values()]
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        effective_mode=effective_mode,
        results=selected[: request.top_k],
        total=len(selected),
        degraded=degradation is not None,
        degradation_reason=degradation,
        embedding_model=MODEL_ID if effective_mode != SearchMode.KEYWORD else None,
        embedding_dimensions=DIMENSIONS if effective_mode != SearchMode.KEYWORD else None,
        candidate_count=len(rows_by_id),
        candidate_limit=limit,
    )
