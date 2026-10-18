"""Tests for chunking, page mapping, and text cleaning.

The policy these tests enforce is written up in
submissions/week07/chunk-policy.md.
"""

from __future__ import annotations

from pathlib import Path

from services.parsing.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    chunk_document,
    clean_page_text,
    strip_running_headers_footers,
)
from services.parsing.pdf import ExtractedDocument, PageText, extract_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def _document(pages: list[str]) -> ExtractedDocument:
    """Build an in-memory document so algorithm tests need no file."""
    return ExtractedDocument(
        content_sha256="0" * 64,
        byte_size=0,
        page_count=len(pages),
        pages=tuple(
            PageText(page_number=index, text=text)
            for index, text in enumerate(pages, start=1)
        ),
    )


# --------------------------------------------------------------------------
# Page mapping
# --------------------------------------------------------------------------


def test_chunks_keep_the_page_they_came_from():
    document = extract_document(FIXTURES / "normal.pdf")
    chunks = chunk_document(document)

    markers = {1: "ALPHA", 2: "BRAVO", 3: "CHARLIE"}
    assert {chunk.page_number for chunk in chunks} == {1, 2, 3}

    for chunk in chunks:
        assert markers[chunk.page_number] in chunk.text, (
            f"chunk {chunk.ordinal} claims page {chunk.page_number} "
            f"but does not contain that page's text"
        )


def test_a_chunk_never_contains_text_from_two_pages():
    # Page 1 and page 2 use different alphabets that share no characters, so a
    # leaked fragment is detectable rather than a matter of judgement.
    page_one = "AAAA " * 200
    page_two = "BBBB " * 200
    chunks = chunk_document(_document([page_one, page_two]))

    for chunk in chunks:
        has_a = "AAAA" in chunk.text
        has_b = "BBBB" in chunk.text
        assert not (has_a and has_b), f"chunk {chunk.ordinal} spans two pages"
        assert (has_a and chunk.page_number == 1) or (has_b and chunk.page_number == 2)


# --------------------------------------------------------------------------
# Size and overlap
# --------------------------------------------------------------------------


def test_a_long_page_splits_into_overlapping_chunks():
    # A page with no break characters at all, so the split points are the hard
    # limits and the overlap is exactly the configured amount.
    page = "abcdefghij" * 300  # 3000 characters, no whitespace or punctuation
    chunks = chunk_document(_document([page]))

    assert len(chunks) > 1
    assert all(chunk.page_number == 1 for chunk in chunks)

    first, second = chunks[0].text, chunks[1].text
    assert first.endswith(second[:CHUNK_OVERLAP_CHARS]), (
        "consecutive chunks on a page must share the configured overlap"
    )


def test_chunk_size_stays_within_the_documented_bound():
    page = "abcdefghij" * 300
    chunks = chunk_document(_document([page]))

    # The policy promises 700 and nothing larger. The tail-folding rule in the
    # chunker allows up to 700 + MIN in principle, but it cannot fire on
    # cleaned text: a page ends on a non-space character, and every later piece
    # starts 120 characters before the previous cut, so a tail is at least 120
    # characters long and never "short". The bound below is the real one.
    assert max(len(chunk.text) for chunk in chunks) <= CHUNK_SIZE_CHARS
    assert all(chunk.text.strip() for chunk in chunks)


def test_no_shape_of_page_produces_a_chunk_over_the_limit():
    """Property-style check over hostile page shapes.

    A single example proves very little, so this builds pages out of words,
    unbroken tokens, short lines, CJK and long paragraphs and asserts the two
    invariants that matter: nothing over 700, and nothing spanning pages.
    """
    import random

    rng = random.Random(20261017)
    for _ in range(300):
        length = rng.choice([1, 79, 80, 120, 699, 700, 701, 780, 1200, 2000])
        style = rng.randrange(5)
        if style == 0:
            text = " ".join(rng.choice(["alpha", "beta", "gamma"]) for _ in range(length // 6 + 1))
        elif style == 1:
            text = "x" * length
        elif style == 2:
            text = "\n".join("line " + "y" * rng.randint(1, 30) for _ in range(length // 20 + 1))
        elif style == 3:
            text = "".join(
                rng.choice("\u6570\u636e \u5e93\u8bbe\u8ba1\n") for _ in range(length // 2)
            )
        else:
            text = "Sentence one. " * (length // 14 + 1)

        chunks = chunk_document(_document([text]))
        assert all(len(chunk.text) <= CHUNK_SIZE_CHARS for chunk in chunks), (
            f"chunk over the limit for style {style}, length {length}: "
            f"{[len(chunk.text) for chunk in chunks]}"
        )
        assert all(chunk.page_number == 1 for chunk in chunks)


def test_short_page_stays_a_single_chunk():
    chunks = chunk_document(_document(["just a short page"]))
    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].ordinal == 1


def test_ordinals_are_sequential_across_pages():
    chunks = chunk_document(_document(["one two three", "four five six"]))
    assert [chunk.ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------


def test_cleaning_joins_hyphenated_line_breaks():
    assert clean_page_text("informa-\ntion") == "information"


def test_cleaning_removes_spaces_between_chinese_characters():
    assert clean_page_text("\u6570 \u636e \u5e93 \u8bbe \u8ba1") == (
        "\u6570\u636e\u5e93\u8bbe\u8ba1"
    )


def test_cleaning_collapses_whitespace_and_blank_lines():
    cleaned = clean_page_text("alpha    beta\t gamma\n\n\n\n\n delta")
    assert "alpha beta gamma" in cleaned
    assert "\n\n\n" not in cleaned


def test_cleaning_keeps_meaningful_english_spacing():
    cleaned = clean_page_text("the quick brown fox")
    assert cleaned == "the quick brown fox"


def test_unmappable_glyphs_are_marked_rather_than_left_as_control_codes():
    """A symbol whose font encoding has no Unicode mapping arrives as a control
    code. Nothing renders it and no search matches it, so it is marked."""
    cleaned = clean_page_text("IDF(t)= log\n\x10\ntotal documents\x11\n= 0.176")

    assert "\x10" not in cleaned
    assert "\x11" not in cleaned
    assert cleaned.count("\ufffd") == 2
    assert "total documents" in cleaned


def test_newlines_survive_cleaning_while_tabs_become_spaces():
    cleaned = clean_page_text("first line\nsecond\tline")
    assert cleaned == "first line\nsecond line"


# --------------------------------------------------------------------------
# Running headers and footers
# --------------------------------------------------------------------------


def test_header_repeated_on_three_pages_is_dropped():
    pages = [
        "MAIE 6000C Lecture\nfirst page body",
        "MAIE 6000C Lecture\nsecond page body",
        "MAIE 6000C Lecture\nthird page body",
    ]
    cleaned = strip_running_headers_footers(pages)

    assert all("MAIE 6000C Lecture" not in page for page in cleaned)
    assert "first page body" in cleaned[0]
    assert "third page body" in cleaned[2]


def test_a_line_that_does_not_repeat_is_kept():
    pages = [
        "Unique opening one\nbody one",
        "Unique opening two\nbody two",
        "Unique opening three\nbody three",
    ]
    cleaned = strip_running_headers_footers(pages)

    assert "Unique opening one" in cleaned[0]
    assert "Unique opening three" in cleaned[2]


def test_short_document_headers_are_left_alone():
    # Fewer than three pages: not enough evidence to call something a header.
    pages = ["Same line\nbody one", "Same line\nbody two"]
    cleaned = strip_running_headers_footers(pages)

    assert all("Same line" in page for page in cleaned)


def test_stripping_a_header_cannot_empty_a_page():
    """A repeated line is only a header because the page has other text.

    Four pages that each contain nothing but "Signature Page" are four
    signature pages, not a document with no content. An independent reviewer
    found that this case produced zero chunks - a document stored as ready with
    nothing in it.
    """
    pages = ["Signature Page"] * 4

    cleaned = strip_running_headers_footers(pages)

    assert cleaned == pages
