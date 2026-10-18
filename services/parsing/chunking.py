"""Turn extracted page text into located, searchable chunks.

Chunking is where retrieval quality is decided. A chunk that is too large
returns a wall of text the user has to read; one that is too small cuts a
sentence in half and matches nothing. Two rules keep this predictable:

1. A chunk never crosses a page boundary. The page is the citation unit, so
   "page 7" must stay exactly true for every chunk on that page. A long page
   simply produces several chunks that all carry the same page number.
2. Consecutive chunks on a page overlap, so a sentence that straddles a cut
   is still readable in at least one chunk.

Splitting prefers a paragraph break, then a sentence end, then whitespace, and
only cuts mid-word when the text offers no better option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.parsing.pdf import ExtractedDocument

# Policy values. Changing these changes retrieval behaviour, so they live in
# one place and are described in docs/chunk-policy.md.
CHUNK_SIZE_CHARS = 700
CHUNK_OVERLAP_CHARS = 120
MIN_CHUNK_CHARS = 80

# How far back from the hard limit we will look for a nicer break.
_BOUNDARY_SEARCH_CHARS = 220

# A line repeated at the same position on this many pages is treated as a
# running header or footer rather than content.
_HEADER_FOOTER_MIN_PAGES = 3
_HEADER_FOOTER_MAX_CHARS = 120

_CJK = r"\u4e00-\u9fff\u3400-\u4dbf"

# C0 control characters that are not layout. They arrive when a font maps a
# symbol to a code with no Unicode meaning, and they are invisible and
# unsearchable in the stored text.
_UNMAPPABLE_GLYPH = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class Chunk:
    """One searchable piece of text, located by page."""

    ordinal: int
    page_number: int
    text: str


def clean_page_text(text: str) -> str:
    """Normalise one page of raw extracted text.

    Handles the noise that PDF text extraction reliably produces: carriage
    returns, words split across a line break with a hyphen, runs of spaces,
    spaces inserted between Chinese characters, and excess blank lines.

    It also marks glyphs that could not be decoded. Some fonts map a symbol -
    a radical sign, a stretched bracket - to a control code with no Unicode
    meaning, and the text arrives carrying that code. Nothing renders it and no
    search matches it, so it is replaced with U+FFFD: the passage then says
    that something was there and could not be read, which is better than a
    character that looks like nothing at all.
    """
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

    # Glyphs with no Unicode mapping arrive as C0 control characters. Tabs and
    # newlines are real layout and stay.
    cleaned = _UNMAPPABLE_GLYPH.sub("\ufffd", cleaned)

    # "informa-\ntion" -> "information"
    cleaned = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", cleaned)

    # Collapse horizontal whitespace runs.
    cleaned = re.sub(r"[ \t\u00a0]+", " ", cleaned)

    # A single space between two CJK characters is an extraction artefact,
    # not meaningful spacing.
    cleaned = re.sub(rf"(?<=[{_CJK}]) (?=[{_CJK}])", "", cleaned)

    # Trim around newlines and collapse blank-line runs to a single break.
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def strip_running_headers_footers(pages: list[str]) -> list[str]:
    """Drop lines that repeat at the top or bottom of most pages.

    Course slides and reports often repeat a title or a footer on every page.
    Left in, that text is indexed on every page and pollutes search results.

    Only the first and last line of each page are considered, and only when the
    identical line appears on at least three pages, which is deliberately
    conservative: a repeated sentence inside the body is kept.
    """
    if len(pages) < _HEADER_FOOTER_MIN_PAGES:
        return pages

    def _edge_lines(position: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for page in pages:
            lines = [line for line in page.split("\n") if line.strip()]
            if not lines:
                continue
            candidate = lines[0] if position == "first" else lines[-1]
            candidate = candidate.strip()
            if not candidate or len(candidate) > _HEADER_FOOTER_MAX_CHARS:
                continue
            counts[candidate] = counts.get(candidate, 0) + 1
        return counts

    common_first = {
        line
        for line, count in _edge_lines("first").items()
        if count >= _HEADER_FOOTER_MIN_PAGES
    }
    common_last = {
        line
        for line, count in _edge_lines("last").items()
        if count >= _HEADER_FOOTER_MIN_PAGES
    }

    result: list[str] = []
    for page in pages:
        lines = page.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        before = list(lines)
        if lines and lines[0].strip() in common_first:
            lines.pop(0)
        if lines and lines[-1].strip() in common_last:
            lines.pop()
        # A line is only a running header because the page has other text. If
        # stripping it would leave the page empty, the line *is* the content -
        # four pages that each say only "Signature Page" are four signature
        # pages, not a document with no text. Without this the rule could empty
        # every page and the document would be stored as ready with no chunks.
        if before and not any(line.strip() for line in lines):
            lines = before
        result.append("\n".join(lines).strip())
    return result


def _find_break(text: str, start: int, hard_end: int) -> int:
    """Choose the best split point at or before ``hard_end``."""
    window_start = max(start + MIN_CHUNK_CHARS, hard_end - _BOUNDARY_SEARCH_CHARS)
    window = text[window_start:hard_end]
    if not window:
        return hard_end

    # Prefer a paragraph break, then a sentence end, then any whitespace.
    for pattern in (r"\n\n", r"[\u3002\uff01\uff1f!?]\s", r"[.;]\s", r"\s"):
        matches = list(re.finditer(pattern, window))
        if matches:
            last = matches[-1]
            return window_start + last.end()

    return hard_end


def _chunk_page_text(text: str) -> list[str]:
    """Split one page of cleaned text into overlapping pieces."""
    if len(text) <= CHUNK_SIZE_CHARS:
        return [text] if text.strip() else []

    pieces: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        hard_end = min(start + CHUNK_SIZE_CHARS, length)
        end = hard_end if hard_end >= length else _find_break(text, start, hard_end)

        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= length:
            break
        # Guarantee forward progress even when the overlap is large.
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)

    # Fold a short tail into the previous chunk rather than emitting a stub,
    # but only while the result stays within the documented size bound. A tail
    # that cannot be folded stays on its own rather than bloating its
    # neighbour.
    if len(pieces) >= 2 and len(pieces[-1]) < MIN_CHUNK_CHARS:
        merged_length = len(pieces[-2]) + 1 + len(pieces[-1])
        if merged_length <= CHUNK_SIZE_CHARS + MIN_CHUNK_CHARS:
            pieces[-2] = f"{pieces[-2]}\n{pieces[-1]}"
            pieces.pop()

    return pieces


def chunk_document(document: ExtractedDocument) -> list[Chunk]:
    """Clean, de-header, and chunk a parsed document in reading order."""
    cleaned = [clean_page_text(page.text) for page in document.pages]
    cleaned = strip_running_headers_footers(cleaned)

    chunks: list[Chunk] = []
    ordinal = 0
    for page, page_text in zip(document.pages, cleaned, strict=True):
        for piece in _chunk_page_text(page_text):
            ordinal += 1
            chunks.append(
                Chunk(ordinal=ordinal, page_number=page.page_number, text=piece)
            )
    return chunks
