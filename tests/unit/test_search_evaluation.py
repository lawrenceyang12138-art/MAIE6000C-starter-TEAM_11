from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from services.common.config import Settings
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    SourceChunk,
)
from services.search.evaluation import evaluate_queries
from services.search.evaluation_sources import resolve_expected
from services.search.text import MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex, text_fingerprint
from tests.support.search import materialize_search_source


class FixedBackend:
    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]


@pytest.fixture()
def corpus(db_session):
    db = db_session
    root = AuthorizedRoot(mount_id="search-fixtures", relative_path=".", status="active")
    db.add(root)
    db.flush()
    files = []

    def add(path="normal/a/manual.pdf", text="needle target", pages=(1,), sha="a" * 64):
        record = FileRecord(
            root_id=root.id, relative_path=path, name=path.rsplit("/", 1)[-1],
            presence_status="present",
        )
        db.add(record)
        db.flush()
        version = FileVersion(
            file_id=record.id, content_sha256=sha, byte_size=100,
            status="basic_ready", parser_revision="parsing-v1",
        )
        db.add(version)
        db.flush()
        record.current_version_id = version.id
        chunks = []
        for ordinal, page in enumerate(pages, 1):
            chunk = SourceChunk(
                version_id=version.id, ordinal=ordinal, page_number=page, text=text,
            )
            db.add(chunk)
            db.flush()
            db.add(ChunkSearchIndex(
                chunk_id=chunk.id, search_text=text,
            ))
            db.add(ChunkTokenIndex(
                chunk_id=chunk.id, model_id=MODEL_ID, model_revision=MODEL_REVISION,
                token_dimensions=TOKEN_DIMENSIONS, token_count=1,
                token_vectors=FixedBackend().embed([text])[0], text_sha256=text_fingerprint(text),
            ))
            chunks.append(chunk)
        materialize_search_source(db, version)
        alias = f"file-{len(files) + 1:03}"
        version_alias = f"version-{len(files) + 1:03}-v1"
        expected = {
            "file_id": alias, "version_id": version_alias,
            "relative_path": path, "page": pages[0], "excerpt": text,
        }
        manifest_record = {
            "file_id": alias, "version_id": version_alias, "relative_path": path,
            "sha256": version.content_sha256, "page_count": max(pages),
            "root_id": "frozen-root-alias",
        }
        files.append(manifest_record)
        db.flush()
        return record, version, chunks, expected

    record, version, chunks, expected = add()
    manifest = {"manifest_version": "test-v1", "root_id": "frozen-root-alias", "files": files}
    return {
        "db": db, "root": root, "file": record, "version": version,
        "chunks": chunks, "expected": expected, "manifest": manifest, "add": add,
    }


def resolve(corpus, expected=None, **kwargs):
    corpus["db"].flush()
    options = {"manifest": corpus["manifest"], "root_id": corpus["root"].id, **kwargs}
    return resolve_expected(
        corpus["db"], expected or corpus["expected"], team_format=True, **options,
    )


def gold(corpus, *, include_keyword=True, include_semantic=True):
    queries = []
    if include_keyword:
        queries.append({
            "query_id": "K01", "kind": "keyword", "query": "needle target",
            "expected": [deepcopy(corpus["expected"])],
        })
    if include_semantic:
        queries.append({
            "query_id": "S01", "kind": "semantic_description", "query": "needle target",
            "expected": [deepcopy(corpus["expected"])],
        })
    return {
        "schema_version": "team11-gold-v1", "frozen_on": "2026-10-16",
        "scope": "Source-location smoke; not a semantic-quality benchmark.",
        "human_review": {"owner": "B", "status": "pending"}, "queries": queries,
    }


def evaluate(corpus, answers=None, **kwargs):
    corpus["db"].flush()
    return evaluate_queries(
        corpus["db"], answers or gold(corpus), Settings(_env_file=None),
        kwargs.pop("backend", FixedBackend()), manifest=corpus["manifest"],
        root_id=corpus["root"].id, **kwargs,
    )


def test_team_aliases_resolve_to_scanner_ids_without_mutating_answers(corpus):
    before = deepcopy(corpus["expected"])
    result = resolve(corpus)
    assert result["ready"] and result["semantic_ready"]
    assert result["file_id"] == corpus["file"].id != before["file_id"]
    assert result["version_id"] == corpus["version"].id != before["version_id"]
    assert result["content_sha256"] == corpus["version"].content_sha256
    assert corpus["expected"] == before


def test_full_relative_path_required_even_with_identical_basename_and_hash(corpus):
    other, _, _, other_expected = corpus["add"]("normal/b/manual.pdf")
    assert resolve(corpus, other_expected)["file_id"] == other.id
    wrong = {**corpus["expected"], "relative_path": "manual.pdf"}
    assert resolve(corpus, wrong)["diagnostics"][0]["code"] == "corpus_mismatch"
    wrong_alias = {**other_expected, "file_id": corpus["expected"]["file_id"]}
    assert resolve(corpus, wrong_alias)["diagnostics"][0]["code"] == "corpus_mismatch"


def test_same_content_in_another_authorized_root_is_not_a_substitute(corpus):
    other_root = AuthorizedRoot(mount_id="other", relative_path=".", status="active")
    corpus["db"].add(other_root)
    corpus["db"].flush()
    result = resolve(corpus, root_id=other_root.id)
    assert result["file_id"] is None
    assert result["diagnostics"][0]["code"] == "corpus_mismatch"


@pytest.mark.parametrize(
    "options,code", [
        ({"root_id": None}, "root_scope_required"),
        ({"manifest": None}, "corpus_manifest_required"),
        ({"root_id": str(uuid4())}, "corpus_mismatch"),
    ],
)
def test_missing_context_has_explicit_diagnostics(corpus, options, code):
    result = resolve(corpus, **options)
    assert not result["ready"]
    assert result["diagnostics"][0]["code"] == code


@pytest.mark.parametrize(
    "path", ["../manual.pdf", "/manual.pdf", "C:/manual.pdf", "normal\\manual.pdf"],
)
def test_non_relative_or_ambiguous_paths_are_rejected(corpus, path):
    result = resolve(corpus, {**corpus["expected"], "relative_path": path})
    assert result["diagnostics"][0]["code"] == "corpus_mismatch"


def test_historical_hash_match_never_substitutes_for_current_version(corpus):
    current = FileVersion(
        file_id=corpus["file"].id, content_sha256="b" * 64,
        byte_size=101, status="basic_ready",
    )
    corpus["db"].add(current)
    corpus["db"].flush()
    corpus["file"].current_version_id = current.id
    result = resolve(corpus)
    assert not result["ready"]
    diagnostic = result["diagnostics"][0]
    assert diagnostic["code"] == "version_mismatch"
    assert diagnostic["historical_version_id"] == corpus["version"].id
    assert result["version_id"] == current.id


def test_frozen_version_alias_disagreement_is_explicit(corpus):
    result = resolve(corpus, {**corpus["expected"], "version_id": "other-version"})
    assert result["diagnostics"][0]["code"] == "version_mismatch"


@pytest.mark.parametrize("page", [0, True, 2])
def test_nonexistent_or_invalid_expected_page_is_not_a_retrieval_miss(corpus, page):
    result = resolve(corpus, {**corpus["expected"], "page": page})
    assert result["diagnostics"][0]["code"] == "expected_page_missing"


def test_frozen_page_without_a_parsed_chunk_is_diagnosed(corpus):
    corpus["manifest"]["files"][0]["page_count"] = 2
    result = resolve(corpus, {**corpus["expected"], "page": 2})
    assert result["diagnostics"][0]["code"] == "expected_page_missing"
    assert result["diagnostics"][0]["parsed_pages"] == [1]


def test_wrong_excerpt_is_a_corpus_mismatch(corpus):
    result = resolve(corpus, {**corpus["expected"], "excerpt": "other source content"})
    assert result["diagnostics"][0]["code"] == "corpus_mismatch"


def test_missing_sidecar_on_another_page_is_not_hidden(corpus):
    _, _, chunks, expected = corpus["add"]("normal/c/manual.pdf", pages=(1, 2))
    corpus["db"].delete(corpus["db"].get(ChunkSearchIndex, chunks[1].id))
    corpus["db"].flush()
    result = resolve(corpus, expected)
    assert result["diagnostics"][0]["code"] == "index_not_ready"
    assert result["chunk_count"] == 2 and result["indexed_chunk_count"] == 1


def test_incompatible_vectors_preserve_keyword_readiness(corpus):
    index = corpus["db"].get(ChunkTokenIndex, corpus["chunks"][0].id)
    index.model_id = "obsolete-model"
    result = resolve(corpus)
    assert result["ready"] and result["keyword_ready"] and not result["semantic_ready"]
    assert result["semantic_diagnostics"][0]["code"] == "index_not_ready"


@pytest.mark.parametrize(
    "target,attribute,value,code", [
        ("root", "status", "revoked", "root_not_authorized"),
        ("file", "presence_status", "missing", "file_missing"),
        ("version", "status", "extracting", "index_not_ready"),
    ],
)
def test_unreadable_sources_are_not_bound_as_ready(corpus, target, attribute, value, code):
    setattr(corpus[target], attribute, value)
    assert resolve(corpus)["diagnostics"][0]["code"] == code


def test_semantic_descriptions_and_hybrid_have_separate_denominators(corpus):
    answers = gold(corpus)
    frozen_copy = deepcopy(answers)
    report = evaluate(corpus, answers)
    assert answers == frozen_copy
    assert report["summary"]["denominators"] == {"keyword": 1, "semantic": 1, "hybrid": 1}
    assert report["summary"]["query_count"] == 2
    assert report["summary"]["search_count"] == 3
    assert report["summary"]["keyword_top1"] == "1/1"
    assert report["summary"]["semantic_top3"] == report["summary"]["hybrid_top3"] == "1/1"
    assert report["team_acceptance"] == "pending_B_review"
    assert report["thresholds"]["freeze_status"] == "C_candidate_not_team_freeze"
    assert report["gold_scope"] == answers["scope"]
    assert report["passed"]
    for row in report["queries"]:
        evidence = row["ranked_results"][0]
        assert evidence["rank"] == 1 and evidence["evidence_matches_result"]
        assert evidence["evidence"]["chunk_id"] == corpus["chunks"][0].id
        assert evidence["evidence"]["text"] == evidence["text"]


def test_fallback_locations_remain_readable_but_are_not_semantic_or_hybrid_hits(corpus):
    report = evaluate(corpus, backend=None)
    assert report["summary"]["keyword_top1"] == "1/1"
    assert report["summary"]["semantic_top3"] == report["summary"]["hybrid_top3"] == "0/1"
    assert report["summary"]["degraded_queries"] == 2
    for row in report["queries"][1:]:
        assert row["location_hit"] and not row["hit"]
        assert row["effective_mode"] == "keyword" and row["degraded"]
        assert row["degradation_reason"] == "ai_unavailable"
        assert row["ranked_results"][0]["evidence_readable"]


def test_expected_array_uses_any_acceptable_location_and_records_every_alternative(corpus):
    _, _, _, alternative = corpus["add"]("normal/b/alternative.pdf", text="unrelated content")
    answers = gold(corpus, include_semantic=False)
    answers["queries"][0]["expected"].insert(0, alternative)
    report = evaluate(corpus, answers)
    row = report["queries"][0]
    assert row["hit"]
    assert len(row["resolved_expected"]) == len(row["expected_matches"]) == 2
    assert [item["location_hit"] for item in row["expected_matches"]] == [False, True]


def test_corpus_mismatch_keeps_original_query_denominators(db_session, corpus):
    report = evaluate_queries(
        db_session, gold(corpus), Settings(_env_file=None), FixedBackend(),
        manifest=corpus["manifest"], root_id=str(uuid4()),
    )
    assert report["summary"]["denominators"] == {"keyword": 1, "semantic": 1, "hybrid": 1}
    assert report["summary"]["source_diagnostics"] == 2
    assert not report["evaluation_valid"] and not report["passed"]
    assert all(row["diagnostics"][0]["code"] == "corpus_mismatch" for row in report["queries"])


@pytest.mark.parametrize("scope", ["missing", "unknown", "revoked"])
def test_invalid_team_scope_never_runs_a_global_or_ai_search(corpus, monkeypatch, scope):
    from services.search import evaluation

    def unexpected_search(*args, **kwargs):
        raise AssertionError("An invalid team scope must not perform a search")

    monkeypatch.setattr(evaluation, "search_chunks", unexpected_search)
    root_id = None if scope == "missing" else str(uuid4())
    if scope == "revoked":
        corpus["root"].status = "revoked"
        corpus["db"].flush()
        root_id = corpus["root"].id
    report = evaluate_queries(
        corpus["db"], gold(corpus), Settings(_env_file=None), FixedBackend(),
        manifest=corpus["manifest"], root_id=root_id,
    )
    assert report["summary"]["denominators"] == {"keyword": 1, "semantic": 1, "hybrid": 1}
    assert report["summary"]["search_count"] == 3
    assert report["summary"]["executed_search_count"] == 0
    assert not report["passed"] and not report["evaluation_valid"]
    for row in report["queries"]:
        assert row["execution_status"] == "not_run_invalid_scope"
        assert row["response"] is None and row["effective_mode"] is None
        assert row["ranked_results"] == [] and row["diagnostics"]


def test_keyword_records_top_three_but_scores_only_top_one(corpus):
    corpus["chunks"][0].text = "needle"
    index = corpus["db"].get(ChunkSearchIndex, corpus["chunks"][0].id)
    index.search_text = "needle"
    corpus["expected"]["excerpt"] = "needle"
    corpus["add"]("normal/b/better.pdf", text="needle target")
    corpus["add"]("normal/c/worse.pdf", text="target")
    report = evaluate(corpus, gold(corpus, include_semantic=False))
    row = report["queries"][0]
    assert len(row["ranked_results"]) == 3
    assert row["evaluation_top_k"] == 1 and row["recorded_top_k"] == 3
    assert row["matched_rank"] in {2, 3} and not row["hit"]


def test_wrong_result_page_does_not_count_even_when_the_file_is_correct(corpus):
    corpus["manifest"]["files"][0]["page_count"] = 2
    chunk = SourceChunk(version_id=corpus["version"].id, ordinal=2, page_number=2, text="other")
    corpus["db"].add(chunk)
    corpus["db"].flush()
    corpus["db"].add(ChunkSearchIndex(
        chunk_id=chunk.id, search_text="other",
    ))
    corpus["db"].add(ChunkTokenIndex(
        chunk_id=chunk.id, model_id=MODEL_ID, model_revision=MODEL_REVISION,
        token_dimensions=TOKEN_DIMENSIONS, token_count=1,
        token_vectors=FixedBackend().embed(["other"])[0], text_sha256=text_fingerprint("other"),
    ))
    answers = gold(corpus, include_keyword=False)
    answers["queries"][0]["expected"][0].update(page=2, excerpt="other")
    report = evaluate(corpus, answers)
    assert all(not row["hit"] for row in report["queries"])
    assert report["queries"][0]["ranked_results"][0]["page"] == 1


def test_inconsistent_evidence_invalidates_a_located_hit(corpus, monkeypatch):
    from services.search import evaluation

    original = evaluation.read_evidence

    def corrupted(db, chunk_id):
        return replace(original(db, chunk_id), text="different original")

    monkeypatch.setattr(evaluation, "read_evidence", corrupted)
    report = evaluate(corpus)
    assert report["summary"]["evidence_failures"] == 3
    assert not report["evaluation_valid"] and not report["passed"]
    assert all(not row["hit"] for row in report["queries"])


def test_legacy_gold_preserves_mode_count_and_explicit_id_mapping(corpus):
    answers = {"queries": [{
        "id": "legacy", "kind": "semantic", "query": "needle",
        "expected_file_id": corpus["file"].id, "expected_page": 1,
    }]}
    report = evaluate(corpus, answers, backend=None)
    assert report["summary"]["search_count"] == 1
    assert report["summary"]["degraded_queries"] == 1
    assert report["summary"]["semantic_top3"] == "0/1"
    assert report["queries"][0]["resolved_expected"][0]["mapping_method"] == "legacy_explicit_id"


def test_semantic_threshold_is_eighty_percent_with_exact_denominator(corpus):
    answers = gold(corpus, include_keyword=False)
    answers["queries"] = [
        {**deepcopy(answers["queries"][0]), "query_id": f"S{index}"} for index in range(6)
    ]
    report = evaluate(corpus, answers)
    assert report["summary"]["semantic_target"] == "5/6"


def test_unknown_gold_kind_is_rejected(corpus):
    answers = gold(corpus)
    answers["queries"][0]["kind"] = "not_a_retrieval_mode"
    with pytest.raises(ValueError, match="Unsupported gold query kind"):
        evaluate(corpus, answers)
