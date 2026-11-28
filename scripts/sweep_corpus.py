"""Run the extractor over a pile of real PDFs it has never seen.

The course decks are three files from one producer. A parser that only ever
meets those is untested, so this sweeps a folder of unrelated documents -
lecture notes, exported slides, scans, whatever is there - and reports what
happened to each.

Two outcomes are both fine and are counted separately:

- **ok** - text came out, with page count, characters and chunk count
- **unsupported** - the document was refused with a reason code, which is a
  property of the document, not a bug

Anything else is an **unexpected error**, and the script exits non-zero for
those: a file that makes the extractor raise is a defect, because the worker
would mark the whole job failed instead of recording why that one document
could not be read.

Usage (inside the api container, with the corpus mounted read-only):

    python scripts/sweep_corpus.py /corpus --limit 40
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.parsing.chunking import chunk_document
from services.parsing.pdf import UnsupportedDocument, extract_document


def _pdfs(targets: list[str]) -> list[Path]:
    found: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            found.extend(sorted(path.rglob("*.pdf")))
        else:
            found.append(path)
    return found


def _control_chars(text: str) -> int:
    """C0 characters that are not layout - invisible and unsearchable."""
    return sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t\r")


def _one(path: Path) -> dict[str, object]:
    try:
        document = extract_document(path)
        chunks = chunk_document(document)
        raw = "\n".join(page.text for page in document.pages)
        # What the user will actually see is the stored chunk text, so the
        # property worth asserting is measured there. The raw count is reported
        # beside it because a document that needs marking is worth knowing
        # about, even when the marking works.
        stored = "\n".join(chunk.text for chunk in chunks)
        return {
            "path": path,
            "outcome": "ok",
            "pages": document.page_count,
            "chars": len(raw),
            "raw_corrupt": raw.count("\ufffd") + _control_chars(raw),
            "stored_control": _control_chars(stored),
            "marked": stored.count("\ufffd"),
            "chunks": len(chunks),
        }
    except UnsupportedDocument as exc:
        return {
            "path": path,
            "outcome": "unsupported",
            "reason": exc.reason_code,
            "message": exc.message,
        }
    except Exception as exc:  # noqa: BLE001 - that is the point of the sweep
        return {
            "path": path,
            "outcome": "UNEXPECTED",
            "error": f"{type(exc).__name__}: {exc}",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", help="PDF files or folders to sweep")
    parser.add_argument("--limit", type=int, default=100, help="stop after N files")
    args = parser.parse_args(argv)

    paths = _pdfs(args.targets)[: args.limit]
    if not paths:
        print("no PDFs found")
        return 2

    rows = [_one(path) for path in paths]

    print(f"{'file':<52}{'outcome':<14}detail")
    print("-" * 100)
    for row in rows:
        name = str(row["path"].name)[:50]
        if row["outcome"] == "ok":
            detail = (
                f"{row['pages']:>4} pages  {row['chars']:>7} chars  "
                f"{row['chunks']:>3} chunks  "
                f"{row['raw_corrupt']} unreadable glyph(s), "
                f"{row['marked']} marked, {row['stored_control']} control left"
            )
        elif row["outcome"] == "unsupported":
            detail = f"{row['reason']} - {row['message'][:44]}"
        else:
            detail = str(row["error"])[:60]
        print(f"{name:<52}{row['outcome']:<14}{detail}")

    ok = [row for row in rows if row["outcome"] == "ok"]
    refused = [row for row in rows if row["outcome"] == "unsupported"]
    broken = [row for row in rows if row["outcome"] == "UNEXPECTED"]

    print()
    print(
        f"{len(rows)} files: {len(ok)} read, {len(refused)} refused with a reason, "
        f"{len(broken)} unexpected"
    )
    if ok:
        print(
            f"pages read: {sum(int(row['pages']) for row in ok)}, "
            f"characters: {sum(int(row['chars']) for row in ok)}, "
            f"unreadable glyphs in the raw text: "
            f"{sum(int(row['raw_corrupt']) for row in ok)}, "
            f"marks in the stored text: {sum(int(row['marked']) for row in ok)} "
            "(overlap can repeat one glyph in two chunks), "
            f"control characters left in the stored text: "
            f"{sum(int(row['stored_control']) for row in ok)}"
        )
    for row in refused:
        print(f"refused: {row['path'].name} - {row['reason']}")
    for row in broken:
        print(f"UNEXPECTED: {row['path'].name} - {row['error']}")

    left_control = sum(int(row["stored_control"]) for row in ok)
    if left_control:
        print(
            f"FAIL: {left_control} control characters reached the stored text, "
            "where nothing can render or match them"
        )
    return 1 if broken or left_control else 0


if __name__ == "__main__":
    sys.exit(main())
