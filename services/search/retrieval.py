from __future__ import annotations

from collections import defaultdict

from sqlalchemy import case, func, literal_column, or_, select
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
    late_interaction_score,
    validate_vectors,
)
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS, normalize_text, tokenize
from services.search.token_store import (
    ChunkTokenIndex,
    index_matches_text,
    token_index_available,
)


def _base_statement(request: SearchRequest, *, include_unindexed: bool = False):
    stmt = (
        select(SourceChunk, ChunkSearchIndex, FileVersion, FileRecord, AuthorizedRoot)
        .join(
            ChunkSearchIndex,
            ChunkSearchIndex.chunk_id == SourceChunk.id,
            isouter=include_unindexed,
        )
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


def _lexical_details(terms, normalized_query, chunk, search_index, source_file):
    matched = sorted(terms.intersection(tokenize(chunk.text)))
    coverage = len(matched) / len(terms) if terms else 0.0
    source_search_text = (
        search_index.search_text if search_index else normalize_text(chunk.text)
    )
    phrase = bool(terms) and normalized_query in source_search_text
    name_match = bool(terms) and normalized_query in normalize_text(source_file.name)
    score = min(
        1.0,
        coverage * 0.8 + (0.2 if phrase else 0) + (0.25 if name_match else 0),
    )
    return score, matched, name_match


def _semantic_candidates(
    db: Session, request: SearchRequest, query_tokens: list[list[float]], limit: int,
    settings: Settings,
):
    """Exact token MaxSim over eligible chunks, bounding only after file grouping.

    The JSON sidecar supports small local corpora on both SQLite and PostgreSQL.
    It does not use the historical 384-dimensional dense vectors, and semantic
    recall is never restricted to chunks matching query keywords. Hybrid mode
    chooses each file's best combined score across every eligible chunk, including
    keyword-only chunks, before applying the file candidate limit.
    """
    if not token_index_available(db):
        return [], {}, False, 0
    statement = (
        _base_statement(request, include_unindexed=True)
        .add_columns(ChunkTokenIndex)
        .outerjoin(ChunkTokenIndex, ChunkTokenIndex.chunk_id == SourceChunk.id)
    )
    best_by_file = {}
    scores = {}
    incomplete = False
    compatible_count = 0
    terms = set(tokenize(request.query))
    normalized_query = normalize_text(request.query)
    weight_sum = settings.search_keyword_weight + settings.search_semantic_weight
    for result in db.execute(statement):
        row, token_index = tuple(result[:5]), result[5]
        chunk, keyword_index, _, source_file, _ = row
        compatible = index_matches_text(token_index, chunk.text)
        if not compatible or keyword_index is None:
            incomplete = True
        if keyword_index is None:
            continue
        if not compatible and request.mode != SearchMode.HYBRID:
            continue
        semantic_score = 0.0
        if compatible:
            compatible_count += 1
            semantic_score = late_interaction_score(query_tokens, token_index.token_vectors)
            scores[chunk.id] = semantic_score
        lexical, _, _ = _lexical_details(
            terms, normalized_query, chunk, keyword_index, source_file,
        )
        score = semantic_score
        if request.mode == SearchMode.HYBRID:
            score = (
                lexical * settings.search_keyword_weight
                + semantic_score * settings.search_semantic_weight
            ) / weight_sum
        key = (-score, -lexical, source_file.id, chunk.ordinal, chunk.id)
        current = best_by_file.get(source_file.id)
        if current is None or key < current[0]:
            best_by_file[source_file.id] = (key, row)
    ordered = sorted(best_by_file.values(), key=lambda item: item[0])
    return [item[1] for item in ordered[:limit]], scores, incomplete, compatible_count


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
    semantic_scores: dict[str, float] = {}
    semantic_rows = []
    effective_mode = request.mode
    if request.mode != SearchMode.KEYWORD:
        if not settings.embedding_enabled:
            degradation = "ai_disabled"
        elif backend is None:
            degradation = "ai_unavailable"
        else:
            try:
                if backend.model_id != MODEL_ID or backend.dimensions != TOKEN_DIMENSIONS:
                    raise EmbeddingUnavailable("embedding_model_mismatch")
                query_tokens = validate_vectors(backend.embed([request.query], "query"), 1)[0]
                semantic_rows, semantic_scores, incomplete, compatible_count = _semantic_candidates(
                    db, request, query_tokens, limit, settings,
                )
                if compatible_count == 0:
                    degradation = "embeddings_not_ready"
                elif incomplete:
                    degradation = "partial_embeddings"
            except EmbeddingUnavailable as exc:
                degradation = str(exc)
        if degradation and degradation != "partial_embeddings":
            effective_mode = SearchMode.KEYWORD

    rows_by_id = {row[0].id: row for row in keyword_rows}
    if effective_mode == SearchMode.SEMANTIC:
        rows_by_id = {row[0].id: row for row in semantic_rows}
    elif effective_mode == SearchMode.HYBRID:
        rows_by_id.update({row[0].id: row for row in semantic_rows})
    terms = set(tokenize(request.query))
    normalized_query = normalize_text(request.query)
    hits: list[SearchResultRead] = []
    for chunk, search_index, version, source_file, root in rows_by_id.values():
        lexical, matched, name_match = _lexical_details(
            terms, normalized_query, chunk, search_index, source_file,
        )
        semantic = (
            semantic_scores.get(chunk.id, 0.0) if effective_mode != SearchMode.KEYWORD else 0.0
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
            reasons.append(f"token MaxSim mean: {semantic:.4f}")
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
                # Keep full precision through ranking and file deduplication.
                # Rounding here can reverse nearby MaxSim scores via ID ties.
                score=min(score, 1.0),
                keyword_score=lexical,
                semantic_score=semantic,
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
    results = [hit.model_copy(update={
        "score": round(hit.score, 6),
        "keyword_score": round(hit.keyword_score, 6),
        "semantic_score": round(hit.semantic_score, 6),
    }) for hit in selected[: request.top_k]]
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        effective_mode=effective_mode,
        results=results,
        total=len(selected),
        degraded=degradation is not None,
        degradation_reason=degradation,
        embedding_model=MODEL_ID if effective_mode != SearchMode.KEYWORD else None,
        embedding_dimensions=TOKEN_DIMENSIONS if effective_mode != SearchMode.KEYWORD else None,
        candidate_count=len(rows_by_id),
        candidate_limit=limit,
    )
