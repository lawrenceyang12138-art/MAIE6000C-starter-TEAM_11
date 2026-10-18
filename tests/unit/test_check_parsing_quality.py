"""The quality-check script is evidence tooling, so it is exercised here too.

If it breaks, the numbers it reports in evidence/pdf-quality.md stop being
reproducible, which is exactly the failure this repository keeps trying to
avoid.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_parsing_quality.py"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"

_spec = importlib.util.spec_from_file_location("check_parsing_quality", SCRIPT)
assert _spec is not None and _spec.loader is not None
quality = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(quality)


def test_scan_reports_clean_text_for_a_normal_pdf():
    scanned = quality._scan(FIXTURES / "normal.pdf")

    assert scanned["pages"] > 0
    assert int(scanned["chars"]) > 0
    assert scanned["replacement"] == 0
    assert scanned["control"] == 0


def test_every_chunk_is_found_on_the_page_it_claims():
    scanned = quality._scan(FIXTURES / "normal.pdf")

    rows = quality._fragments(scanned, 5)

    assert rows, "no fragments were checked"
    for position, page, chars, found, doubles, short, opening in rows:
        assert found, f"fragment {position} is not on page {page}: {opening!r}"
        assert chars > 0
        assert doubles == 0, "cleaning should have collapsed runs of spaces"
