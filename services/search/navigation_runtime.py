"""Read-only page decisions over already eligible canonical source versions."""

from __future__ import annotations

from dataclasses import asdict

from services.common.schemas import SearchMode
from services.search.page_metadata import load_page_metadata
from services.search.page_navigation import parse_page_intent, target_pages

NAVIGATION_PROFILE = "pplx_page_navigation_v1"
PLAIN_PROFILE = "pplx_only"


class PageNavigation:
    def __init__(self, query: str, enabled: bool, mode: SearchMode):
        parsed = parse_page_intent(query)
        self.intent = parsed.intent
        self.active = enabled and mode != SearchMode.KEYWORD and self.intent is not None
        reason = (
            "disabled" if not enabled else "keyword_mode" if mode == SearchMode.KEYWORD
            else parsed.skipped_reason
        )
        self.report = {
            "enabled": enabled,
            "profile": NAVIGATION_PROFILE if enabled else PLAIN_PROFILE,
            "intent": asdict(self.intent) if self.intent else None,
            "parse_status": parsed.skipped_reason or "recognized",
            "status": "not_applied",
            "not_applied_reason": reason,
            "files": [],
        }
        self.by_version: dict[str, dict] = {}

    def allows(self, db, chunk, version, source_file) -> bool:
        if not self.active:
            return True
        decision = self.by_version.get(version.id)
        if decision is None:
            count, metadata_status = load_page_metadata(db, version)
            pages = target_pages(self.intent, count) if count is not None else ()
            reason = metadata_status if count is None else (
                "single_page_required" if not pages and self.intent.kind == "single"
                else "page_out_of_range" if not pages else "target_page_selected"
            )
            decision = {
                "file_id": source_file.id,
                "version_id": version.id,
                "page_count": count,
                "metadata_status": metadata_status,
                "target_pages": list(pages),
                "applied": count is not None,
                "reason": reason,
                "eligible_chunk_count": 0,
                "target_chunk_count": 0,
                "selected_chunk_id": None,
                "selected_page": None,
            }
            self.by_version[version.id] = decision
            self.report["files"].append(decision)
        decision["eligible_chunk_count"] += 1
        allowed = not decision["applied"] or chunk.page_number in decision["target_pages"]
        if allowed and decision["applied"]:
            decision["target_chunk_count"] += 1
        return allowed

    def fallback(self, reason: str) -> None:
        self.active = False
        self.report.update(status="not_applied", not_applied_reason=reason, files=[])
        self.by_version.clear()

    def finish(self, rows) -> None:
        if not self.active:
            return
        applied = [item for item in self.by_version.values() if item["applied"]]
        self.report["status"] = (
            "applied" if applied and len(applied) == len(self.by_version)
            else "partially_applied" if applied else "not_applied"
        )
        self.report["not_applied_reason"] = (
            None if applied else "page_metadata_unavailable" if self.by_version
            else "no_eligible_chunks"
        )
        for decision in applied:
            if decision["target_pages"] and not decision["target_chunk_count"]:
                decision["reason"] = "target_page_without_text_chunk"
        for row in rows:
            chunk, _, version, _, _ = row
            decision = self.by_version.get(version.id)
            if decision is not None:
                decision["selected_chunk_id"] = chunk.id
                decision["selected_page"] = chunk.page_number

    def reason(self, version_id: str) -> str | None:
        if not self.active:
            skipped = self.report["not_applied_reason"]
            return (
                "page navigation not applied: " + skipped
                if skipped in {"negated", "conflicting", "range", "unsupported"} else None
            )
        decision = self.by_version.get(version_id)
        if decision is None:
            return None
        if not decision["applied"]:
            return "page navigation not applied: " + decision["metadata_status"]
        return (
            f"page navigation: {self.intent.kind}; physical page {decision['selected_page']}"
            f" of {decision['page_count']}"
        )
