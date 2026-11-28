"""Guards for the card that goes on the slide.

The card is a picture of evidence, so the two ways it could mislead are worth
pinning: drawing something that was never checked, and printing characters the
font turns into question marks - which would put mojibake on the one artefact
that claims there is none.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "render_evidence_card.py"

_spec = importlib.util.spec_from_file_location("render_evidence_card", SCRIPT)
assert _spec is not None and _spec.loader is not None
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


def test_the_search_phrase_is_the_opening_words():
    assert card._opening("Live Demo Step 2: Create a Case Through") == (
        "Live Demo Step 2: Create a"
    )


def test_caption_text_is_ascii_safe():
    caption = card._ascii("Week 5 \u2014 Lab \u2022 Dr. Chen\u2019s notes")

    assert caption == "Week 5 - Lab * Dr. Chen's notes"
    assert "?" not in caption
    assert all(ord(char) < 256 for char in caption)


def test_without_a_renderer_the_card_refuses(monkeypatch, capsys):
    monkeypatch.setattr(card, "_renderer", lambda: None)

    exit_code = card.main(["/nonexistent.pdf", "--out", "/tmp/never-written.jpg"])

    assert exit_code == 2
    assert "refused" in capsys.readouterr().out
    assert not Path("/tmp/never-written.jpg").exists()
