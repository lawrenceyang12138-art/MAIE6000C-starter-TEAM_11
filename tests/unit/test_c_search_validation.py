from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from scripts import c_search_suite as corpus
from scripts.verify_c_search import Run, evidence_matches, score_rows, summarize_quality, timings
from services.search.page_metadata import PAGE_METADATA_POLICY
from services.search.text import MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS
from services.search.token_store import text_fingerprint


def test_frozen_suite_has_valid_sources_and_a_separate_load_profile(tmp_path, monkeypatch):
    suite = corpus.load_suite()
    corpus.check_originals(suite)
    plan = corpus.corpus_plan(suite)
    assert len(plan) == 28
    assert len(suite["queries"]) == 17
    assert suite["freeze"]["human_b_review"] == "pending"
    assert suite["freeze"]["team_threshold"] is None
    counts = {
        lang: sum(row["kind"] == "topical" and row["language"] == lang for row in suite["queries"])
        for lang in ("en", "zh")
    }
    assert counts == {"en": 6, "zh": 6}
    larger = corpus.corpus_plan(suite, 7)
    assert len(larger) == 112
    assert {path for path in larger if not path.startswith("load/")} == set(plan)

    staging = tmp_path / "staging"
    monkeypatch.setattr(corpus, "STAGING", staging)
    path = staging / "quality"
    corpus.stage(path, plan)
    corpus.stage(path, plan)  # Exact staged data is reusable.
    original_path = next(iter(plan))
    original = corpus.REPO / plan[original_path]["fixture_path"]
    original_hash = corpus.digest(original)
    (path / original_path).write_bytes(b"incorrect fixture")
    with pytest.raises(corpus.SuiteError, match="staged bytes differ"):
        corpus.stage(path, plan)
    assert corpus.digest(original) == original_hash
    with pytest.raises(corpus.SuiteError, match="only a direct child"):
        corpus.stage(tmp_path / "outside", plan)


def test_freeze_rejects_an_edited_answer_before_scoring(tmp_path):
    for name in ("manifest.json", "queries.json", "freeze.json"):
        shutil.copyfile(corpus.FIXTURE / name, tmp_path / name)
    gold = json.loads((tmp_path / "queries.json").read_bytes())
    gold["queries"][0]["expected"][0]["page"] = 2
    (tmp_path / "queries.json").write_text(json.dumps(gold), encoding="utf-8")
    with pytest.raises(corpus.SuiteError, match="frozen queries hash mismatch"):
        corpus.load_suite(tmp_path)


@pytest.mark.parametrize("path", ["../a.pdf", "/a.pdf", "C:/a.pdf", "a\\b.pdf", "a//b.pdf"])
def test_corpus_paths_are_portable_and_relative(tmp_path, path):
    with pytest.raises(corpus.SuiteError, match="invalid corpus path"):
        corpus.safe_path(tmp_path, path)


def test_quote_score_does_not_treat_file_or_page_as_supporting_passage():
    gold = [{"path": "a.pdf", "page": 2, "quote": "expected  passage"}]
    candidates = [
        {"verified": True, "path": "a.pdf", "page": 1, "text": "other page"},
        {"verified": False, "path": "a.pdf", "page": 2, "text": "expected passage"},
        {"verified": True, "path": "a.pdf", "page": 2, "text": "other passage"},
    ]
    first = score_rows(gold, candidates, 1)
    assert (first["file_hit"], first["page_hit"], first["quote_hit"]) == (True, False, False)
    top3 = score_rows(gold, candidates, 3)
    assert top3["first_rank"] == {"file": 1, "page": 3, "quote": None}
    assert (top3["file_hit"], top3["page_hit"], top3["quote_hit"]) == (True, True, False)
    assert score_rows(gold, [dict(candidates[2], text="expected\npassage")], 1)["quote_hit"]


def test_evidence_rejects_wrong_source_hash_or_identity():
    hit = SimpleNamespace(
        file_id="f",
        version_id="v",
        chunk_id="c",
        file_path="a.pdf",
        page=2,
        ordinal=3,
        text="verified passage",
    )
    good = dict(
        file_id="f",
        version_id="v",
        chunk_id="c",
        relative_path="a.pdf",
        page_number=2,
        ordinal=3,
        text="verified passage",
        content_sha256="frozen",
    )
    assert evidence_matches(hit, good, {"sha256": "frozen"})
    for change in ({"content_sha256": "wrong"}, {"page_number": 3}, {"chunk_id": "different"}):
        assert not evidence_matches(hit, good | change, {"sha256": "frozen"})


def test_quality_denominators_and_latency_are_not_pooled():
    def row(kind, language, mode, cutoff, hit):
        return dict(
            kind=kind,
            language=language,
            mode=mode,
            cutoff=cutoff,
            file_hit=hit,
            page_hit=hit,
            quote_hit=hit,
        )

    groups = summarize_quality(
        [
            row("source_smoke", "en", "keyword", 1, True),
            row("topical", "en", "keyword", 3, True),
            row("topical", "zh", "keyword", 3, False),
        ]
    )
    assert [(g["kind"], g["language"], g["queries"], g["quote_hits"]) for g in groups] == [
        ("source_smoke", "all", 1, 1),
        ("topical", "all", 2, 1),
        ("topical", "en", 1, 1),
        ("topical", "zh", 1, 0),
    ]
    assert timings([float(i) for i in range(1, 21)]) == {
        "samples": 20,
        "median_ms": 10.5,
        "p95_ms": 19.0,
        "max_ms": 20.0,
    }


@pytest.mark.parametrize("phase", ["prepare", "finish", "load"])
@pytest.mark.parametrize("missing_page", [False, True], ids=["complete", "missing-non-answer"])
def test_validate_state_covers_each_current_searchable_page(phase, missing_page):
    suite = corpus.load_suite()
    engine = MagicMock()
    options = SimpleNamespace(phase=phase, load_copies=int(phase == "load"))
    run = Run(options, None, engine, suite, {})
    atlas = "topics/north/atlas.pdf"
    assert {
        loc["page"] for q in suite["queries"] for loc in q["expected"] if loc["path"] == atlas
    } == {2}
    target = f"load/batch-01/{atlas}" if phase == "load" else atlas
    enriched = phase != "prepare"
    ready_status = "enriched" if enriched else "basic_ready"
    state = dict(
        files=[],
        versions=[],
        chunks=[],
        jobs=[{"status": "completed"}],
        relationships=[],
        reviews=[],
    )
    metadata = []
    for index, (path, source) in enumerate(run.plan.items(), 1):
        file_id, version_id = f"file-{index}", f"version-{index}"
        state["files"].append(
            dict(
                id=file_id,
                current_version_id=version_id,
                relative_path=path,
                presence_status="present",
            )
        )
        ready = source["status"] == "ready"
        content = dict(content_sha256=source["sha256"], byte_size=source["byte_size"])
        state["versions"].append(
            dict(
                id=version_id,
                file_id=file_id,
                **content,
                status=ready_status if ready else source["status"],
                error_code=source["error_code"],
            )
        )
        if not ready:
            continue
        metadata.append(
            dict(
                version_id=version_id,
                **content,
                page_count=source["page_count"],
                policy_revision=PAGE_METADATA_POLICY,
                parser_revision="v1",
                parser="v1",
            )
        )
        pages = list(range(1, source["page_count"] + 1))
        if path == target:
            # An extra chunk on the answer page can hide the gap in aggregate counts.
            pages.append(2)
            if missing_page:
                pages.remove(1)
        state["chunks"].extend(
            dict(
                id=f"{version_id}-{ordinal}",
                version_id=version_id,
                ordinal=ordinal,
                page_number=page,
                text=f"Fixture passage {ordinal}",
            )
            for ordinal, page in enumerate(pages, 1)
        )

    state["page_metadata"] = metadata
    state["keyword_indexes"] = [{"chunk_id": row["id"]} for row in state["chunks"]]
    state["token_indexes"] = state["keyword_indexes"] if enriched else []
    tokens = [
        dict(
            chunk_id=row["id"],
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            token_dimensions=TOKEN_DIMENSIONS,
            matrix_rows=1,
            token_count=1,
            text_sha256=text_fingerprint(row["text"]),
        )
        for row in state["chunks"]
        if enriched
    ]
    engine.connect.return_value.__enter__.return_value.execute.side_effect = [
        Mock(**{"mappings.return_value.all.return_value": rows}) for rows in (tokens, metadata)
    ]

    if missing_page:
        with pytest.raises(corpus.SuiteError, match=f"missing chunk for {target} physical page 1"):
            run.validate_state("root", state, enriched=enriched)
    else:
        assert set(run.validate_state("root", state, enriched=enriched)) == set(run.plan)
