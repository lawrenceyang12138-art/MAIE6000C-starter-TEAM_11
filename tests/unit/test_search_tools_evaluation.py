"""Exercise the public evaluation CLI's frozen-input preflight boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from services.search.token_store import ChunkTokenIndex

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "submissions/week07/gold-queries.json"
MANIFEST = REPO / "fixtures/manifest.json"
FREEZE = REPO / "submissions/week07/gold-queries.freeze.json"


def test_prepare_token_index_cli_adds_only_derived_storage_without_loading_ai(db_session, tmp_path):
    engine = db_session.get_bind()
    ChunkTokenIndex.__table__.drop(engine, checkfirst=True)
    before = set(inspect(engine).get_table_names())
    assert "source_chunks" in before
    completed = subprocess.run([
        sys.executable, "-m", "scripts.search_tools", "prepare-token-index",
        "--database-url", str(engine.url), "--backend", "local",
        "--model-path", str(tmp_path / "missing-model"),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "canonical tables unchanged" in completed.stdout
    assert set(inspect(engine).get_table_names()) - before == {ChunkTokenIndex.__tablename__}


@pytest.mark.parametrize(
    "changed_input,code", [
        ("gold", "frozen_gold_hash_mismatch"),
        ("manifest", "frozen_manifest_hash_mismatch"),
    ],
)
def test_frozen_mismatch_cli_stops_before_database_or_ai_creation(tmp_path, changed_input, code):
    gold, manifest = tmp_path / "gold.json", tmp_path / "manifest.json"
    gold.write_bytes(GOLD.read_bytes())
    manifest.write_bytes(MANIFEST.read_bytes())
    selected = gold if changed_input == "gold" else manifest
    # Valid JSON with identical decoded answers, but distinct frozen bytes.
    selected.write_bytes(selected.read_bytes() + b"\n")
    preserved = {path: path.read_bytes() for path in (gold, manifest, FREEZE)}
    output = tmp_path / "preflight.json"
    completed = subprocess.run([
        sys.executable, "-m", "scripts.search_tools", "evaluate",
        # This nonexistent dialect makes any engine construction fail. A
        # complete structured preflight report proves execution stops earlier.
        "--database-url", "nonexistent+driver://user:private-password@localhost/db",
        "--gold", str(gold), "--manifest", str(manifest), "--freeze", str(FREEZE),
        "--root-id", str(uuid4()), "--backend", "local",
        "--model-path", str(tmp_path / "model-does-not-exist"), "--output", str(output),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
    assert completed.returncode == 1, completed.stderr
    assert "Traceback" not in completed.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["status"] == "preflight_failed"
    assert not report["passed"] and not report["candidate_gate_passed"]
    assert not report["evaluation_valid"] and not report["freeze_verified"]
    assert report["queries"] == []
    assert [item["code"] for item in report["diagnostics"]] == [code]
    diagnostic = report["diagnostics"][0]
    assert diagnostic["expected_sha256"] != diagnostic["actual_sha256"]
    assert "private-password" not in json.dumps(report)
    assert {path: path.read_bytes() for path in preserved} == preserved


def test_matching_freeze_cli_preserves_team_shape_and_scope_denominators(db_session, tmp_path):
    output = tmp_path / "matching-freeze.json"
    completed = subprocess.run([
        sys.executable, "-m", "scripts.search_tools", "evaluate",
        "--database-url", str(db_session.get_bind().url),
        "--gold", str(GOLD), "--manifest", str(MANIFEST), "--freeze", str(FREEZE),
        "--root-id", str(uuid4()), "--backend", "off", "--output", str(output),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
    assert completed.returncode == 1, completed.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["freeze_verified"]
    assert report["summary"]["denominators"] == {"keyword": 5, "semantic": 5, "hybrid": 5}
    assert report["summary"]["executed_search_count"] == 0
    assert len(report["queries"]) == 15
    assert all(item["query_id"] and item["expected"] for item in report["queries"])
    assert all(item["response"] is None for item in report["queries"])
    assert all(item["execution_status"] == "not_run_invalid_scope" for item in report["queries"])
    assert not report["passed"]


@pytest.mark.parametrize("protected", ["gold", "manifest", "freeze"])
def test_evaluation_cli_refuses_overwriting_frozen_inputs(tmp_path, protected):
    paths = {name: tmp_path / (name + ".json")
             for name in ("gold", "manifest", "freeze")}
    for name, original in (("gold", GOLD), ("manifest", MANIFEST), ("freeze", FREEZE)):
        paths[name].write_bytes(original.read_bytes())
    preserved = {name: path.read_bytes() for name, path in paths.items()}
    completed = subprocess.run([
        sys.executable, "-m", "scripts.search_tools", "evaluate",
        "--database-url", "nonexistent+driver://localhost/db",
        "--gold", str(paths["gold"]), "--manifest", str(paths["manifest"]),
        "--freeze", str(paths["freeze"]), "--output", str(paths[protected]),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
    assert completed.returncode == 2
    assert "output_path_conflict" in completed.stderr
    assert {name: path.read_bytes() for name, path in paths.items()} == preserved


def test_runtime_cli_refuses_overwriting_its_evaluation(tmp_path):
    prior = tmp_path / "evaluation.json"
    prior.write_text("{}", encoding="utf-8")
    completed = subprocess.run([
        sys.executable, "-m", "scripts.verify_team_search_runtime",
        "--database-url", "nonexistent+driver://localhost/db",
        "--evaluation", str(prior), "--output", str(prior),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
    assert completed.returncode == 2
    assert "output_path_conflict" in completed.stderr
    assert prior.read_text("utf-8") == "{}"
