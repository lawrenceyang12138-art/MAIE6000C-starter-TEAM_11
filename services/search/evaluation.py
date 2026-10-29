from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from math import ceil
from time import perf_counter

from sqlalchemy.orm import Session

from services.common.config import Settings
from services.common.models import AuthorizedRoot
from services.common.schemas import SearchRequest
from services.parsing.evidence import SourceUnavailable, read_evidence
from services.search.embeddings import EmbeddingBackend
from services.search.evaluation_sources import expected_locations, resolve_expected
from services.search.retrieval import search_chunks
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS


def _ranked_evidence(db: Session, response) -> list[dict]:
    ranked = []
    for rank, item in enumerate(response.results, 1):
        row = {"rank": rank, **item.model_dump(mode="json")}
        try:
            evidence = read_evidence(db, item.chunk_id)
            row["evidence"] = asdict(evidence)
            row["evidence_readable"] = True
            row["evidence_matches_result"] = (
                evidence.file_id == item.file_id
                and evidence.version_id == item.version_id
                and evidence.page_number == item.page
                and evidence.ordinal == item.ordinal
                and evidence.relative_path == item.file_path
                and evidence.text[:2000] == item.text
            )
        except SourceUnavailable as exc:
            row["evidence_readable"] = row["evidence_matches_result"] = False
            row["evidence_error"] = exc.reason_code
        ranked.append(row)
    return ranked


def evaluate_queries(
    db: Session,
    gold: dict,
    settings: Settings,
    backend: EmbeddingBackend | None,
    *,
    manifest: dict | None = None,
    root_id: str | None = None,
    modes: tuple[str, ...] | None = None,
) -> dict:
    """Measure unchanged answers against scoped, current source evidence.

    ``expected`` is a set of acceptable locations: one correct located result is
    a hit. Every alternative is resolved and reported; invalid corpus entries
    never disappear from denominators. Team semantic descriptions run semantic
    and hybrid Top-3 separately. Legacy hand-authored gold keeps its old default
    mode set. ``passed`` is C's candidate gate, never team acceptance.
    """
    allowed_modes = ("keyword", "semantic", "hybrid")
    if modes is not None and (not modes or not set(modes) <= set(allowed_modes)):
        raise ValueError("modes must contain keyword, semantic and/or hybrid")
    rows = []
    counts = dict.fromkeys(allowed_modes, 0)
    hits = dict.fromkeys(allowed_modes, 0)
    degraded = duplicates = evidence_failures = source_diagnostic_count = 0
    resolution_rows = []
    runtime_root = db.get(AuthorizedRoot, root_id) if root_id else None
    for query in gold["queries"]:
        kind = query["kind"]
        if kind not in {"keyword", "semantic", "semantic_description", "hybrid"}:
            raise ValueError(f"Unsupported gold query kind: {kind}")
        team_format = "expected" in query
        locations = expected_locations(query)
        resolved = [resolve_expected(
            db, item, team_format=team_format, manifest=manifest, root_id=root_id,
        ) for item in locations]
        query_id = query.get("query_id", query.get("id"))
        resolution_rows.append({"query_id": query_id, "expected": locations, "resolved": resolved})
        source_diagnostic_count += sum(len(item["diagnostics"]) for item in resolved)
        natural_modes = ("keyword",) if kind == "keyword" else (
            ("hybrid",) if kind == "hybrid" else ("semantic", "hybrid")
        )
        if not team_format and modes is None:
            natural_modes = (kind,)
        selected_modes = [mode for mode in natural_modes if modes is None or mode in modes]
        invalid_scope = team_format and (
            runtime_root is None or runtime_root.status not in {"active", "paused"}
        )
        for mode in selected_modes:
            counts[mode] += 1
            start = perf_counter()
            response = None
            if not invalid_scope:
                response = search_chunks(
                    db,
                    SearchRequest(query=query["query"], mode=mode, top_k=3, root_id=root_id),
                    settings,
                    backend,
                )
            ranked = _ranked_evidence(db, response) if response is not None else []
            evidence_failures += sum(not item["evidence_matches_result"] for item in ranked)
            cutoff = 1 if mode == "keyword" else 3
            expected_matches = []
            for location in resolved:
                location_ranks = [item["rank"] for item in ranked if (
                    location["ready"]
                    and item["file_id"] == location["file_id"]
                    and item["version_id"] == location["version_id"]
                    and item["root_id"] == location["root_id"]
                    and item["page"] == location["page"]
                    and item["evidence_matches_result"]
                )]
                expected_matches.append({
                    "expected": location["expected"],
                    "file_id": location["file_id"],
                    "version_id": location["version_id"],
                    "page": location["page"],
                    "rank": min(location_ranks) if location_ranks else None,
                    "location_hit": any(rank <= cutoff for rank in location_ranks),
                })
            location_hit = any(item["location_hit"] for item in expected_matches)
            model_ran = (
                response is not None and response.effective_mode == mode and not response.degraded
            )
            hit = location_hit and (mode == "keyword" or model_ran)
            hits[mode] += int(hit)
            degraded += int(response.degraded) if response is not None else 0
            duplicate_count = len(ranked) - len({item["file_id"] for item in ranked})
            duplicates += duplicate_count
            diagnostics = [diagnostic for item in resolved for diagnostic in item["diagnostics"]]
            if mode != "keyword":
                diagnostics += [
                    diagnostic for item in resolved for diagnostic in item["semantic_diagnostics"]
                ]
            ranks = [item["rank"] for item in expected_matches if item["rank"] is not None]
            rows.append({
                **query,
                "query_id": query_id,
                "requested_mode": mode,
                "execution_status": "not_run_invalid_scope" if invalid_scope else "executed",
                "effective_mode": response.effective_mode.value if response is not None else None,
                "degraded": response.degraded if response is not None else False,
                "degradation_reason": response.degradation_reason if response is not None else None,
                "evaluation_top_k": cutoff,
                "recorded_top_k": 3,
                "resolved_expected": resolved,
                "expected_matches": expected_matches,
                "diagnostics": diagnostics,
                "location_hit": location_hit,
                "hit": hit,
                "matched_rank": min(ranks) if ranks else None,
                "duplicate_files": duplicate_count,
                "seconds": round(perf_counter() - start, 4),
                "response": response.model_dump(mode="json") if response is not None else None,
                "ranked_results": ranked,
            })
    semantic_target = ceil(counts["semantic"] * 0.8)
    candidate_gate = (
        hits["keyword"] == counts["keyword"]
        and hits["semantic"] >= semantic_target
        and duplicates == 0
        and evidence_failures == 0
        and bool(counts["keyword"] or counts["semantic"])
    )
    evaluation_valid = source_diagnostic_count == 0 and evidence_failures == 0
    review = gold.get("human_review", {"status": "not_applicable"})
    team_format = any("expected" in query for query in gold["queries"])
    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "report_schema": "c-scoped-evaluation-v2",
        "data_kind": gold.get(
            "data_kind", "team_pdf_source_location_smoke" if team_format else "unspecified",
        ),
        "gold_schema_version": gold.get("schema_version"),
        "answers_frozen_at": gold.get("frozen_on", gold.get("frozen_at")),
        "gold_scope": gold.get("scope", gold.get("description")),
        "human_review": review,
        "team_acceptance": (
            "pending_B_review" if review.get("status") == "pending" else "not_established"
        ),
        "expected_policy": "any_acceptable_location_file_version_page; all alternatives diagnosed",
        "model": MODEL_ID,
        "dimensions": TOKEN_DIMENSIONS,
        "representation": "token_multivector",
        "scoring": "maxsim_mean",
        "corpus": {
            "manifest_version": manifest.get("manifest_version") if manifest else None,
            "manifest_root_alias": manifest.get("root_id") if manifest else None,
            "runtime_root_id": root_id,
            "identity_policy": (
                "authorized_root_uuid + exact_relative_path + current_content_sha256"
            ),
        },
        "summary": {
            "keyword_top1": f"{hits['keyword']}/{counts['keyword']}",
            "semantic_top3": f"{hits['semantic']}/{counts['semantic']}",
            "hybrid_top3": f"{hits['hybrid']}/{counts['hybrid']}",
            "semantic_target": f"{semantic_target}/{counts['semantic']}",
            "query_count": len(gold["queries"]),
            "search_count": len(rows),
            "executed_search_count": sum(row["execution_status"] == "executed" for row in rows),
            "denominators": counts,
            "hits": hits,
            "degraded_queries": degraded,
            "duplicate_files": duplicates,
            "evidence_failures": evidence_failures,
            "source_diagnostics": source_diagnostic_count,
        },
        "thresholds": {
            "keyword_top1_rate": 1.0,
            "semantic_top3_rate": 0.8,
            "semantic_target_for_five": "4/5",
            "freeze_status": "C_candidate_not_team_freeze",
            "hybrid": "reported_separately_no_team_threshold_frozen",
        },
        "parameters": {
            "keyword_weight": settings.search_keyword_weight,
            "semantic_weight": settings.search_semantic_weight,
            "candidate_limit_per_channel": settings.search_max_candidates,
            "recorded_top_k": 3,
            "keyword_evaluation_top_k": 1,
            "semantic_hybrid_evaluation_top_k": 3,
            "ai_request_timeout_seconds": settings.search_request_timeout_seconds,
        },
        "evaluation_valid": evaluation_valid,
        "candidate_gate_passed": candidate_gate,
        "passed": candidate_gate and evaluation_valid,
        "source_resolutions": resolution_rows,
        "queries": rows,
    }
