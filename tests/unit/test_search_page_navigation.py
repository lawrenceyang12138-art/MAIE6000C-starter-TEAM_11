"""Navigation grammar tests; runtime code never reads these frozen answers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from services.search.page_navigation import PageIntent, parse_page_intent, target_pages

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "fixtures/search/page-navigation-v1.json"
FREEZE = json.loads((REPO / "fixtures/search/page-navigation-v1.freeze.json").read_text("utf-8"))
FIXTURE = json.loads(FIXTURE_PATH.read_text("utf-8"))
DOCUMENTS = {item["id"]: item for item in FIXTURE["documents"]}


def test_frozen_navigation_fixture_identity_and_denominators():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FREEZE["fixture_sha256"]
    assert Counter(case["group"] for case in FIXTURE["cases"]) == {"positive": 24, "negative": 12}
    assert len({case["id"] for case in FIXTURE["cases"]}) == 36


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda item: item["id"])
def test_frozen_navigation_grammar_and_physical_targets(case):
    parsed = parse_page_intent(case["query"])
    if case["intent"] is None:
        assert parsed.intent is None
        assert parsed.skipped_reason == case["skipped"]
        return
    assert parsed.intent == PageIntent(case["intent"], case.get("page"))
    assert parsed.skipped_reason is None
    count = DOCUMENTS[case["document"]]["page_count"]
    # An explicit request can be outside the document; its valid target is empty.
    if "target_pages" in case:
        expected = tuple(page for page in case["target_pages"] if 1 <= page <= count)
        assert target_pages(parsed.intent, count) == expected


@pytest.mark.parametrize("query,expected", [
    ("查看第一百零二页", 102),
    ("打开第一千二百三十四页", 1234),
    ("第两千零九页", 2009),
    ("第九千九百九十九页", 9999),
    ("打开第〇页", None),
    ("打开第一百三页", None),
    ("打开第一二页", None),
    ("查看第十十页", None),
    ("查看第零十页", None),
    ("Open page 0", None),
    ("Open page -1", None),
    ("Open page +2", None),
    ("Open page 2.5", None),
    ("Open page infinity", None),
    ("Open page 99999999999999999999999", None),
    ("Open the 11st page", None),
    ("Open the 21st page", 21),
    ("Show the twelfth leaf", 12),
])
def test_explicit_numerals_reject_malformed_or_unsupported_values(query, expected):
    parsed = parse_page_intent(query)
    if expected is None:
        assert parsed.intent is None
        assert parsed.skipped_reason == "unsupported"
    else:
        assert parsed.intent == PageIntent("absolute", expected)


@pytest.mark.parametrize("query,reason", [
    ("Do not open the last page", "negated"),
    ("Don't open page 2", "negated"),
    ("Exclude the opening leaf", "negated"),
    ("不用打开最后一页", "negated"),
    ("Show page 1 and page 3", "conflicting"),
    ("打开第一页以及最后一页", "conflicting"),
    ("Show the first, middle and last pages", "conflicting"),
    ("Open the first or last leaf", "conflicting"),
    ("Open page 2 or 3", "range"),
    ("Open the 2nd to 4th page", "range"),
    ("打开第2至第4页", "range"),
    ("查看最后三页", "range"),
    ("Open the first 3 pages", "range"),
    ("查找最后更新的中间件与第三章", "no_intent"),
    ("Open the eleventh report", "no_intent"),
    ("Show the middle of the report", "no_intent"),
    ("Find webpage metadata", "no_intent"),
])
def test_ambiguous_and_non_page_context_stays_ordinary(query, reason):
    parsed = parse_page_intent(query)
    assert parsed.intent is None
    assert parsed.skipped_reason == reason


@pytest.mark.parametrize("query", [
    "第一页 first page", "Show page 2 and page 2", "打开最后一页 final page",
])
def test_consistent_repeated_instructions_are_not_conflicts(query):
    assert parse_page_intent(query).intent is not None


@pytest.mark.parametrize("count,expected", [(1, (1,)), (2, (1, 2)), (3, (2,)), (4, (2, 3)),
                                             (7, (4,)), (10, (5, 6))])
def test_even_middle_has_two_physical_candidates(count, expected):
    assert target_pages(PageIntent("middle"), count) == expected


@pytest.mark.parametrize("count", [None, 0, -1, True, 3.0, "3"])
def test_unknown_or_invalid_page_count_has_no_targets(count):
    assert target_pages(PageIntent("last"), count) == ()


def test_requested_page_never_clamps_to_nearest_available_page():
    assert target_pages(PageIntent("absolute", 9), 3) == ()
    assert target_pages(PageIntent("absolute", None), 3) == ()
    assert target_pages(PageIntent("absolute", True), 3) == ()
    assert target_pages(PageIntent("single"), 2) == ()
