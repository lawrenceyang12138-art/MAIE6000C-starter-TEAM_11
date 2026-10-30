"""Both supported pytest entry points must collect repository script tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_TESTS = (
    "tests/unit/test_search_model_preparation.py",
    "tests/unit/test_search_page_metadata_cli.py",
    "tests/integration/test_team_pdf_evaluation.py",
)


@pytest.mark.parametrize("entrypoint", ["console", "module"])
def test_pytest_entrypoints_collect_script_imports_without_external_pythonpath(entrypoint):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTEST_ADDOPTS", None)
    if entrypoint == "console":
        name = "pytest.exe" if os.name == "nt" else "pytest"
        command = [str(Path(sysconfig.get_path("scripts")) / name)]
    else:
        command = [sys.executable, "-m", "pytest"]
    completed = subprocess.run(
        [*command, "--collect-only", "-q", *SCRIPT_TESTS],
        cwd=REPO, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ModuleNotFoundError" not in completed.stdout + completed.stderr
    for path in SCRIPT_TESTS:
        assert path in completed.stdout.replace("\\", "/")
