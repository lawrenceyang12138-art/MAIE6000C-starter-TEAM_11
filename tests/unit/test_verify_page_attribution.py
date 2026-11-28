"""The page check must not be able to pass by grading itself.

The script's whole value is that a second PDF library judges the first one's
output. It used to fall back to the pipeline's own extractor when PyMuPDF was
missing, which turned a missing dependency into a green result. That is the
kind of failure nobody notices, so it is pinned here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_page_attribution.py"

# The script is not an installed package, so it is loaded from its path.
_spec = importlib.util.spec_from_file_location("verify_page_attribution", SCRIPT)
assert _spec is not None and _spec.loader is not None
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def test_without_a_second_reader_the_check_refuses_to_run(monkeypatch):
    monkeypatch.setattr(verifier, "_independent_reader", lambda: None)

    with pytest.raises(verifier.NoIndependentReader):
        verifier._reference_pages(str(FIXTURES / "normal.pdf"))


def test_the_self_check_escape_hatch_is_labelled(monkeypatch):
    monkeypatch.setattr(verifier, "_independent_reader", lambda: None)

    name, pages = verifier._reference_pages(
        str(FIXTURES / "normal.pdf"), allow_self_check=True
    )

    assert "NOT independent" in name
    assert pages and any(page.strip() for page in pages)


def test_the_real_reader_is_preferred_when_it_is_installed():
    """Only meaningful where PyMuPDF exists; the refusal above covers the rest."""
    if verifier._independent_reader() is None:
        pytest.skip("PyMuPDF is not installed in this image")

    name, pages = verifier._reference_pages(str(FIXTURES / "normal.pdf"))

    assert name == "PyMuPDF (independent)"
    assert pages and any(page.strip() for page in pages)
