from __future__ import annotations

from collections import defaultdict

from sqlalchemy import case, exists, func, literal_column, or_, select
from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.models import SourceChunk, SourceFile, SourceVersion
from services.common.schemas import SearchMode, SearchRequest, SearchResponse, SearchResultRead
from services.search.embeddings import (
    EmbeddingBackend,
    EmbeddingUnavailable,
    cosine_similarity,
    validate_vectors,
)
from services.search.text import DIMENSIONS, MODEL_ID, normalize_text, tokenize


def _base_statement(file_id: str | None = None):
    stmt = (
        select(SourceChunk, SourceVersion, SourceFile)
        .join(SourceVersion, SourceChunk.source_version_id == SourceVersion.id)
        .join(SourceFile, SourceVersion.source_file_id == SourceFile.id)
        .where(
            SourceVersion.is_current.is_(True),
            SourceVersion.status == "ready",
            SourceFile.status == "ready",
            SourceFile.sha256 == SourceVersion.sha256,
        )
    )
    if file_id is not None:
        stmt = stmt.where(SourceFile.id == file_id)
    return stmt


def _bounded_candidates(db: Session, base, score, predicate, limit: int):
    """Limit after choosing a chunk per file, so one long PDF cannot hide other files."""
    ranked = (
        base.with_only_columns(
            SourceChunk.id.label("chunk_id"),
            score.label("rank_score"),
            func.row_number()
            .over(
                partition_by=SourceFile.id,
                order_by=(score.desc(), SourceChunk.chunk_index, SourceChunk.id),
            )
            .label("file_rank"),
        )
        .where(predicate)
        .subquery()
    )
    ids = (
        select(ranked.c.chunk_id)
        .where(ranked.c.file_rank == 1)
        .order_by(
            ranked.c.rank_score.desc(),
            ranked.c.chunk_id,
        )
        .limit(limit)
    )
    return list(db.execute(base.where(SourceChunk.id.in_(ids))))


def _keyword_candidates(db: Session, base, query: str, limit: int):
    terms = tokenize(query)
    if not terms:
        return []
    phrase_match = SourceChunk.search_text.contains(normalize_text(query), autoescape=True)
    name_match = func.lower(SourceFile.name).contains(normalize_text(query), autoescape=True)
    coverage = sum(
        case((SourceChunk.search_terms.contains(f" {term} ", autoescape=True), 1.0), else_=0.0)
        for term in terms
    ) / len(terms)
    score = coverage * 0.8 + case((phrase_match, 0.2), else_=0.0)
    score += case((name_match, 0.25), else_=0.0)
    if db.bind.dialect.name == "postgresql":
        document = func.to_tsvector(literal_column("'simple'"), SourceChunk.search_terms)
        ts_query = func.to_tsquery(literal_column("'simple'"), " | ".join(terms))
        predicate = or_(document.op("@@")(ts_query), name_match)
    else:
        predicate = or_(coverage > 0, name_match)
    return _bounded_candidates(db, base, score, predicate, limit)


def _semantic_candidates(db: Session, base, vector: list[float], limit: int):
    matching_model = (
        (SourceChunk.embedding.is_not(None))
        & (SourceChunk.embedding_model == MODEL_ID)
        & (SourceChunk.embedding_dimensions == DIMENSIONS)
        & (SourceVersion.embedding_model == MODEL_ID)
        & (SourceVersion.embedding_dimensions == DIMENSIONS)
    )
    if db.bind.dialect.name == "postgresql":
        score = 1.0 - SourceChunk.embedding.cosine_distance(vector)
        return _bounded_candidates(db, base, score, matching_model, limit)
    # SQLite is a unit-test/development adapter. Production uses pgvector's <=> operator.
    rows = list(db.execute(base.where(matching_model)))
    rows.sort(
        key=lambda row: (
            -cosine_similarity(vector, row[0].embedding),
            row[0].chunk_index,
            row[0].id,
        )
    )
    seen: set[str] = set()
    result = []
    for row in rows:
        if row[2].id not in seen:
            result.append(row)
            seen.add(row[2].id)
        if len(result) >= limit:
            break
    return result


def search_chunks(
    db: Session,
    request: SearchRequest,
    settings: Settings,
    backend: EmbeddingBackend | None,
) -> SearchResponse:
    base = _base_statement(request.file_id)
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
        # Both semantic modes must disclose an incomplete vector index.
        incomplete = base.with_only_columns(SourceChunk.id).where(
            or_(
                SourceChunk.embedding.is_(None),
                SourceChunk.embedding_model.is_(None),
                SourceChunk.embedding_model != MODEL_ID,
                SourceChunk.embedding_dimensions.is_(None),
                SourceChunk.embedding_dimensions != DIMENSIONS,
                SourceVersion.embedding_model.is_(None),
                SourceVersion.embedding_model != MODEL_ID,
                SourceVersion.embedding_dimensions.is_(None),
                SourceVersion.embedding_dimensions != DIMENSIONS,
            )
        )
        if db.scalar(select(exists(incomplete))):
            degradation = "partial_embeddings"

    terms = set(tokenize(request.query))
    normalized_query = normalize_text(request.query)
    hits: list[SearchResultRead] = []
    for chunk, version, source_file in rows_by_id.values():
        matched = sorted(terms.intersection(tokenize(chunk.text)))
        coverage = len(matched) / len(terms) if terms else 0.0
        phrase = bool(terms) and normalized_query in chunk.search_text
        name_match = bool(terms) and normalized_query in normalize_text(source_file.name)
        lexical = min(1.0, coverage * 0.8 + (0.2 if phrase else 0) + (0.25 if name_match else 0))
        semantic = 0.0
        if (
            vector is not None
            and chunk.embedding is not None
            and chunk.embedding_model == MODEL_ID
            and chunk.embedding_dimensions == DIMENSIONS
            and version.embedding_model == MODEL_ID
            and version.embedding_dimensions == DIMENSIONS
        ):
            semantic = max(0.0, cosine_similarity(vector, list(chunk.embedding)))
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
                file_id=source_file.id,
                file_name=source_file.name,
                file_path=source_file.path,
                version_id=version.id,
                version_number=version.version_number,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
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
            hit.chunk_index,
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
