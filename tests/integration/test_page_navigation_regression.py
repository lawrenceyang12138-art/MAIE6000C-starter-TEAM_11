"""The frozen navigation cases use actual PDFs, not manufactured source chunks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from services.common.models import AuthorizedRoot

REPO = Path(__file__).resolve().parents[2]


def run_cli(*arguments: str):
    return subprocess.run(
        [sys.executable, "-m", "scripts.verify_page_navigation", *arguments], cwd=REPO,
        capture_output=True, text=True, encoding="utf-8", timeout=90, check=False,
    )


def test_frozen_navigation_regression_uses_real_pdf_pipeline_and_fails_safely(tmp_path):
    output, corpus = tmp_path / "report.json", tmp_path / "pdfs"
    completed = run_cli("--database-url", f"sqlite:///{tmp_path / 'navigation.db'}",
                        "--work-dir", str(corpus), "--output", str(output))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["passed"] and report["source_bytes_unchanged"]
    assert not report["model_inference"]
    assert report["scoring_evidence"] == "hand_constructed_token_vectors_not_PPLX_inference"
    assert report["summary"]["positive"] == {"passed": 24, "total": 24}
    assert report["summary"]["negative"] == {"passed": 12, "total": 12}
    assert report["summary"]["enhanced_executions"] == 72
    assert report["summary"]["baseline_executions"] == 72
    assert report["summary"]["passed_executions"] == 72
    assert report["summary"]["evidence_failures"] == 0
    assert report["summary"]["diagnostic_failures"] == 0
    assert report["scan"]["files_created"] == 11
    assert len(report["fault_injections"]) == 3
    assert all(item["status"] == "basic_ready" for item in report["pipeline"])
    assert sum(item["index"]["chunk_count"] for item in report["pipeline"]) > 43
    cases = {case["id"]: case for case in report["cases"]}
    for case_id in ("P03", "P09", "P11", "P22"):
        semantic = cases[case_id]["executions"][0]
        assert semantic["baseline_response"]["results"][0]["page"] == 1
        assert semantic["response"]["results"][0]["page"] in cases[case_id]["target_pages"]
    for case_id in ("N06", "N07", "N08", "N11", "N12"):
        assert all(not execution["response"]["results"]
                   for execution in cases[case_id]["executions"])
    assert cases["N07"]["stored_page_count"] == 4
    assert cases["N09"]["metadata_status"] == "page_metadata_missing"
    assert cases["N10"]["metadata_status"] == "page_metadata_stale"
    rerun = run_cli("--database-url", f"sqlite:///{tmp_path / 'navigation.db'}",
                    "--work-dir", str(corpus), "--output", str(tmp_path / "repeat.json"))
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    repeated = json.loads((tmp_path / "repeat.json").read_text("utf-8"))
    assert repeated["root_id"] == report["root_id"]
    assert repeated["scan"]["files_created"] == 0
    assert repeated["source_files"] == report["source_files"]


def test_navigation_runner_refuses_other_roots_before_corpus_or_database_writes(
    db_session, tmp_path,
):
    foreign = AuthorizedRoot(mount_id="other-role", relative_path=".", status="active")
    db_session.add(foreign)
    db_session.commit()
    corpus, output = tmp_path / "pdfs", tmp_path / "refused.json"
    completed = run_cli("--database-url", str(db_session.get_bind().url),
                        "--work-dir", str(corpus), "--output", str(output))
    assert completed.returncode == 1, completed.stdout + completed.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["failure"]["code"] == "navigation_database_contains_other_roots"
    assert not corpus.exists()
    assert list(db_session.scalars(select(AuthorizedRoot.id))) == [foreign.id]


def test_navigation_runner_refuses_output_inside_source_before_generating_pdf(tmp_path):
    corpus = tmp_path / "pdfs"
    completed = run_cli("--database-url", f"sqlite:///{tmp_path / 'navigation.db'}",
                        "--work-dir", str(corpus), "--output", str(corpus / "report.json"))
    assert completed.returncode == 2
    assert "output_path_inside_source" in completed.stderr
    assert not corpus.exists()
