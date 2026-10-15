"""Reproduce the parsing quality numbers recorded in evidence/pdf-quality.md.

Two checks, both on real PDFs rather than fixtures:

  1. A character-level scan of every page: how much text came out, whether any
     replacement characters (dropped glyphs) or control characters (mojibake)
     appeared, and how many line-end hyphens the cleaning rules had to judge.
  2. The first N chunks of the first document, each checked against the page it
     claims: is its full text really there, has whitespace been normalised, and
     how many lines are shorter than a title fragment.

Usage (inside the api container):

    python scripts/check_parsing_quality.py /fixtures/*.pdf
    python scripts/check_parsing_quality.py /fixtures/a.pdf --fragments 20

Exits non-zero if any replacement or control character appears, or if a chunk
cannot be found on the page it claims. A number nobody can re-run is not
evidence, and this file exists so these numbers are.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from services.parsing.chunking import (
    chunk_document,
    clean_page_text,
    strip_running_headers_footers,
)
from services.parsing.pdf import extract_document

# A line this short is a title fragment rather than prose. The threshold was
# chosen because it reproduces the table in evidence/pdf-quality.md exactly;
# changing it changes how many fragments the table reports.
SHORT_LINE = 15

REPLACEMENT = "\ufffd"
KEEP_CONTROL = {"\n", "\t", "\r"}
LINE_END_HYPHEN = re.compile(r"-\n")


def _scan(path: Path) -> dict[str, object]:
    document = extract_document(path)
    raw_pages = [page.text for page in document.pages]
    joined = "\n".join(raw_pages)
    chunks = chunk_document(document)

    # The pipeline cleans a page first and applies the running-header rule
    # second. Measuring the rule on raw text instead counts blank lines it
    # trims, which are not content: on this corpus that mistake reports three
    # changed pages where the real answer is none.
    cleaned_pages = [clean_page_text(page) for page in raw_pages]
    stripped_pages = strip_running_headers_footers(list(cleaned_pages))
    headers_removed = sum(
        1 for before, after in zip(cleaned_pages, stripped_pages) if before != after
    )

    return {
        "name": path.name,
        "pages": document.page_count,
        "chars": len(joined),
        "replacement": joined.count(REPLACEMENT),
        "control": sum(
            1 for char in joined if ord(char) < 32 and char not in KEEP_CONTROL
        ),
        "line_end_hyphens": len(LINE_END_HYPHEN.findall(joined)),
        "headers_removed": headers_removed,
        "chunks": len(chunks),
        "raw_pages": raw_pages,
        "chunks_list": chunks,
    }


def _fragments(scanned: dict[str, object], count: int) -> list[tuple]:
    raw_pages = scanned["raw_pages"]
    chunks = scanned["chunks_list"]
    rows = []
    for position, chunk in enumerate(chunks[:count], start=1):
        page_text = clean_page_text(raw_pages[chunk.page_number - 1])
        lines = chunk.text.split("\n")
        rows.append(
            (
                position,
                chunk.page_number,
                len(chunk.text),
                chunk.text in page_text,
                chunk.text.count("  "),
                sum(1 for line in lines if len(line) < SHORT_LINE),
                " ".join(chunk.text.split())[:40],
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="PDF files to check")
    parser.add_argument(
        "--fragments",
        type=int,
        default=20,
        help="how many chunks of the first file to list (default 20)",
    )
    args = parser.parse_args(argv)

    scanned = [_scan(Path(name)) for name in args.pdfs]

    print("character scan")
    print(
        f"{'file':<40}{'pages':<7}{'chars':<8}{'repl':<6}{'ctrl':<6}"
        f"{'hyphens':<9}{'headers':<9}chunks"
    )
    print("-" * 92)
    for row in scanned:
        print(
            f"{str(row['name'])[:38]:<40}{row['pages']:<7}{row['chars']:<8}"
            f"{row['replacement']:<6}{row['control']:<6}"
            f"{row['line_end_hyphens']:<9}{row['headers_removed']:<9}"
            f"{row['chunks']}"
        )
    print()
    print("chars counts the raw per-page text joined with newlines, before cleaning")
    print(
        "headers counts pages whose text the running-header rule changed, "
        "measured after cleaning"
    )

    rows = _fragments(scanned[0], args.fragments)
    print()
    print(f"first {len(rows)} chunks of {scanned[0]['name']}, against their pages")
    print(
        f"{'#':<4}{'page':<6}{'chars':<7}{'on page':<10}{'dbl sp':<8}"
        f"{'short':<7}opening"
    )
    print("-" * 82)
    for position, page, chars, found, doubles, short, opening in rows:
        print(
            f"{position:<4}{page:<6}{chars:<7}{'yes' if found else 'NO':<10}"
            f"{doubles:<8}{short:<7}{opening}"
        )

    total_chars = sum(int(row["chars"]) for row in scanned)
    bad_chars = sum(int(row["replacement"]) + int(row["control"]) for row in scanned)
    missing = [row for row in rows if not row[3]]
    print()
    print(
        f"{len(scanned)} files, {sum(int(r['pages']) for r in scanned)} pages, "
        f"{total_chars} characters, {bad_chars} corrupt characters"
    )
    print(f"fragments found on their page: {len(rows) - len(missing)}/{len(rows)}")

    if bad_chars or missing:
        print("FAIL: corrupt characters or misplaced fragments")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
