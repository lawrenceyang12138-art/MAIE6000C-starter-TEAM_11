"""Evidence collection must not depend on a Windows console's text encoding."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

from scripts import evaluate_team_pdf


def test_git_state_decodes_display_as_utf8_and_hashes_raw_diff_bytes(monkeypatch):
    diff = b"diff --git a/doc b/doc\n+" + "首次启动下载与预热".encode() + b"\xff\n"
    calls = []

    def git_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        assert "text" not in kwargs
        assert "encoding" not in kwargs
        if arguments[1] == "diff":
            output = diff
        elif arguments[1] == "status":
            output = b" M docs/" + "准备进度".encode() + b".md\n"
        else:
            output = b"test-sha-or-branch\n"
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(evaluate_team_pdf.subprocess, "run", git_run)
    state = evaluate_team_pdf.git_state()
    assert state["sha"] == "test-sha-or-branch"
    assert state["working_tree_status"] == "M docs/准备进度.md"
    assert state["tracked_diff_sha256"] == hashlib.sha256(diff.strip()).hexdigest()
    assert len(calls) == 4


def test_unavailable_git_still_produces_safe_reproducibility_fields(monkeypatch):
    monkeypatch.setattr(
        evaluate_team_pdf.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b""),
    )
    state = evaluate_team_pdf.git_state()
    assert state["sha"] == "unavailable"
    assert state["branch"] == "unavailable"
    assert state["working_tree_status"] == "unavailable"
    assert state["tracked_diff_sha256"] == hashlib.sha256(b"unavailable").hexdigest()


def test_runtime_without_git_still_fingerprints_the_evaluated_sources(monkeypatch):
    def git_not_installed(*args, **kwargs):
        raise FileNotFoundError("git is not installed in the runtime image")

    monkeypatch.setattr(evaluate_team_pdf.subprocess, "run", git_not_installed)
    state = evaluate_team_pdf.git_state()
    assert state["sha"] == state["branch"] == state["working_tree_status"] == "unavailable"
    assert state["source_sha256"]["scripts/evaluate_team_pdf.py"] == hashlib.sha256(
        Path(evaluate_team_pdf.__file__).read_bytes()
    ).hexdigest()
