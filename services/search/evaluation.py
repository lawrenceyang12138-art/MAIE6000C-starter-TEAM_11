from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.schemas import SearchRequest
from services.search.embeddings import EmbeddingBackend
from services.search.retrieval import search_chunks
from services.search.text import DIMENSIONS, MODEL_ID


def evaluate_queries(
    db: Session,
    gold: dict,
    settings: Settings,
    backend: EmbeddingBackend | None,
) -> dict:
    """Record frozen answers unchanged; degraded semantic results never count as semantic hits."""
    rows = []
    keyword_hits = semantic_hits = degraded = duplicates = 0
    for query in gold["queries"]:
        kind = query["kind"]
        start = perf_counter()
        response = search_chunks(
            db,
            SearchRequest(
                query=query["query"],
                mode=kind,
                top_k=3,
            ),
            settings,
            backend,
        )
        results = response.results
        hit = any(
            item.file_id == query["expected_file_id"]
            and item.page == query["expected_page"]
            for item in (results[:1] if kind == "keyword" else results)
        )
        if kind == "semantic" and (
            response.effective_mode != "semantic" or response.degraded
        ):
            hit = False
        keyword_hits += int(hit and kind == "keyword")
        semantic_hits += int(hit and kind == "semantic")
        degraded += int(response.degraded)
        duplicate_count = len(results) - len({item.file_id for item in results})
        duplicates += duplicate_count
        rows.append(
            {
                **query,
                "hit": hit,
                "seconds": round(perf_counter() - start, 4),
                "response": response.model_dump(mode="json"),
            }
        )
    keyword_count = sum(item["kind"] == "keyword" for item in gold["queries"])
    semantic_count = sum(item["kind"] == "semantic" for item in gold["queries"])
    semantic_target = min(4, semantic_count)
    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "data_kind": gold.get("data_kind", "unspecified"),
        "model": MODEL_ID,
        "dimensions": DIMENSIONS,
        "summary": {
            "keyword_top1": f"{keyword_hits}/{keyword_count}",
            "semantic_top3": f"{semantic_hits}/{semantic_count}",
            "semantic_target": f"{semantic_target}/{semantic_count}",
            "degraded_queries": degraded,
            "duplicate_files": duplicates,
        },
        "parameters": {
            "keyword_weight": settings.search_keyword_weight,
            "semantic_weight": settings.search_semantic_weight,
            "candidate_limit_per_channel": settings.search_max_candidates,
        },
        "passed": keyword_hits == keyword_count
        and semantic_hits >= semantic_target
        and duplicates == 0,
        "queries": rows,
    }
