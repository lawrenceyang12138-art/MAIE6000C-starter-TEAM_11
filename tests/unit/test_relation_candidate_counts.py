"""The line-initial rule has to be measurable, not just asserted.

The evidence file quotes three numbers per document - candidates with the rule
off, with it on, and after bounding - and those numbers are also spoken on the
slides. The switch that produces the first of them is what these tests hold in
place.
"""

from __future__ import annotations

from services.parsing.chunking import Chunk
from services.parsing.relations import find_mentions


def test_a_line_initial_single_word_is_dropped_by_default():
    chunk = Chunk(ordinal=0, page_number=1, text="Project\nnotes about things")

    assert find_mentions([chunk]) == []


def test_the_same_word_is_kept_when_the_rule_is_disabled():
    chunk = Chunk(ordinal=0, page_number=1, text="Project\nnotes about things")

    mentions = find_mentions([chunk], skip_line_initial=False)

    assert [mention.label for mention in mentions] == ["Project"]
    assert mentions[0].entity_type == "project"


def test_disabling_the_rule_can_only_add_candidates():
    chunks = [
        Chunk(ordinal=0, page_number=1, text="Project\nnotes about things"),
        Chunk(ordinal=1, page_number=2, text="More notes.\nPlatform\nand so on"),
    ]

    with_rule = find_mentions(chunks)
    without_rule = find_mentions(chunks, skip_line_initial=False)

    assert len(without_rule) >= len(with_rule)
    assert {mention.label for mention in with_rule} <= {
        mention.label for mention in without_rule
    }
