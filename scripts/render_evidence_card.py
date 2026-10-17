"""Render the slide B talks over: the real page, with our stored passage on it.

Slide 4 promises a picture of a stored passage beside the page it claims, and
the interface that would show that does not exist yet - the routes belong to
member A. This produces the same picture from the artefacts instead of from a
screenshot of a screen that does not exist: the page is rendered from the
original PDF by PyMuPDF, and the box is drawn where the independently rendered
page text contains the passage we stored.

Nothing here is drawn by hand. If the passage cannot be found on the rendered
page, the script says so and exits non-zero rather than producing a picture
that implies a match which was not checked.

Usage (inside the api container, with PyMuPDF installed):

    pip install --quiet PyMuPDF
    python scripts/render_evidence_card.py "/fixtures/Week 5 — Lab.pdf" \
        --page 6 --out submissions/week07/artifacts/page-evidence.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.parsing.chunking import chunk_document
from services.parsing.pdf import extract_document

# How much of the passage is searched for on the page. A whole chunk spans
# lines and never matches as one string, so the opening words are used.
SEARCH_WORDS = 6

# Rendering scale. A slide is placed at roughly a third of a 1920-wide screen,
# so 1.5x of a 960-point page is already more pixels than the deck will use;
# going higher only makes the file bigger.
DEFAULT_ZOOM = 1.5

# Space under the page for the passage and where it came from, so the card
# carries its own provenance instead of relying on the speaker to say it.
CAPTION_HEIGHT = 250
CAPTION_PADDING = 24
CAPTION_FONT = 17

# The built-in fonts are Latin-1, so an em dash in a file name would come out
# as a question mark in the caption. Normalise the caption to ASCII instead of
# shipping a card with mojibake on it, which is the one thing this page is
# supposed to prove does not happen.
_ASCII_REPLACEMENTS = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2022": "*",
    "\u00b7": ".",
    "\u00a0": " ",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
}


def _ascii(text: str) -> str:
    for original, replacement in _ASCII_REPLACEMENTS.items():
        text = text.replace(original, replacement)
    return text.encode("latin-1", "replace").decode("latin-1")


class NoRenderer(RuntimeError):
    """PyMuPDF is not available, so no page can be rendered."""


def _renderer():
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            return None
    return pymupdf


def _opening(passage: str) -> str:
    words = passage.split()
    return " ".join(words[:SEARCH_WORDS])


def _compose(renderer, pixmap, chunk, page_number, page_count, source, sha256, hits):
    """Lay the rendered page above a caption strip naming what it shows."""
    width = pixmap.width + CAPTION_PADDING * 2
    height = pixmap.height + CAPTION_HEIGHT
    card = renderer.open()
    page = card.new_page(width=width, height=height)

    page.insert_image(
        renderer.Rect(CAPTION_PADDING, CAPTION_PADDING, pixmap.width, pixmap.height),
        pixmap=pixmap,
    )

    found = "found on this page" if hits else "NOT found on this page"
    passage = " ".join(chunk.text.split())[:104]
    caption = _ascii(
        "\n".join(
            [
                f"stored passage - page {page_number} of {page_count}, "
                f"chunk ordinal {chunk.ordinal}",
                f'"{passage}"',
                "",
                f"source      {source}",
                f"content     sha256 {sha256[:16]}",
                f"page text   {found} by a PDF library the pipeline does not use",
            ]
        )
    )
    page.insert_textbox(
        renderer.Rect(
            CAPTION_PADDING,
            pixmap.height + CAPTION_PADDING,
            width - CAPTION_PADDING,
            height - CAPTION_PADDING,
        ),
        caption,
        fontsize=CAPTION_FONT,
        fontname="cour",
    )
    return card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="source PDF")
    parser.add_argument("--page", type=int, default=1, help="page number to render")
    parser.add_argument("--out", required=True, help="path for the PNG")
    parser.add_argument(
        "--zoom",
        type=float,
        default=DEFAULT_ZOOM,
        help=f"rendering scale (default {DEFAULT_ZOOM})",
    )
    parser.add_argument(
        "--chunk-ordinal",
        type=int,
        default=None,
        help="which chunk of that page to highlight (default: the first one)",
    )
    args = parser.parse_args(argv)

    renderer = _renderer()
    if renderer is None:
        print(
            "refused: PyMuPDF is not installed, so the page cannot be rendered. "
            "Install it (pip install PyMuPDF)."
        )
        return 2

    document = extract_document(args.pdf)
    chunks = [
        chunk for chunk in chunk_document(document) if chunk.page_number == args.page
    ]
    if not chunks:
        print(f"refused: no stored passage claims page {args.page}")
        return 2

    chunk = (
        chunks[args.chunk_ordinal]
        if args.chunk_ordinal is not None and args.chunk_ordinal < len(chunks)
        else chunks[0]
    )
    opening = _opening(chunk.text)

    pdf = renderer.open(args.pdf)
    page = pdf[args.page - 1]
    hits = page.search_for(opening)

    if hits:
        annot = page.add_highlight_annot(hits[0])
        annot.set_colors(stroke=(1, 0.9, 0.2))
        annot.update()

    pixmap = page.get_pixmap(matrix=renderer.Matrix(args.zoom, args.zoom))
    card = _compose(
        renderer,
        pixmap,
        chunk,
        args.page,
        document.page_count,
        Path(args.pdf).name,
        document.content_sha256,
        hits,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # The composed page is written through a pixmap so the extension decides
    # the format: a JPEG keeps the file small enough to drop into a deck.
    composed = card[0].get_pixmap(matrix=renderer.Matrix(1, 1))
    if out.suffix.lower() in {".jpg", ".jpeg"}:
        composed.save(str(out), jpg_quality=90)
    else:
        composed.save(str(out))

    print(f"page:     {args.page} of {document.page_count}")
    print(f"passage:  {chunk.text[:70]!r}")
    print(f"searched: {opening!r}")
    print(f"found:    {len(hits)} match(es) on the rendered page")
    print(f"written:  {out} ({out.stat().st_size} bytes)")
    print(f"source:   {Path(args.pdf).name}, sha256 {document.content_sha256[:8]}")

    if not hits:
        print("FAIL: the passage was not found on the page it claims")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
