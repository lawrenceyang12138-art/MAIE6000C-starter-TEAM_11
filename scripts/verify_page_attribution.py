"""Independently verify that stored passages really sit on the pages they claim.

This is a check of B's own work, so it must not use B's own extraction to do
the checking: re-running the same code and comparing it with itself proves
nothing. Instead each stored passage is looked for in a page extracted by a
*different* tool than the one the pipeline uses.

Reference extractor: PyMuPDF, a different library entirely. Without it the
script exits 2 rather than quietly checking the pipeline against itself; the
`--allow-self-check` flag runs it anyway using raw pypdf page text, which
shares the library but bypasses cleaning and chunking, and labels the result
as not independent.

Every row prints two identifiers: the version row id, which the database
creates fresh on each run, and the content hash of the bytes the passage was
read from, which a reader can check against their own copy of the file.

Usage (inside the api container):

    python scripts/verify_page_attribution.py /fixtures/a.pdf /fixtures/b.pdf

A scratch root named ``verify-page-attribution`` is created and refreshed on
each run, so this can be repeated without leaving stray rows behind.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from services.common.db import get_session_factory
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
)
from services.parsing.handler import handle_extract_file
from services.parsing.pdf import extract_document, file_identity

SCRATCH_MOUNT_ID = "verify-page-attribution"
WINDOW = 30
FRACTIONS = (0.25, 0.5, 0.75)

SELF_CHECK_REFUSED = (
    "PyMuPDF is not installed, so the only reader available is the one under "
    "test. Comparing our own extraction with itself proves nothing, and this "
    "script will not print a pass for it. Install it (pip install PyMuPDF), or "
    "pass --allow-self-check to get a result that is explicitly not "
    "independent."
)


class NoIndependentReader(RuntimeError):
    """The check cannot be run honestly with what is installed."""


def _independent_reader():
    try:
        import pymupdf  # PyMuPDF, current import name
    except ImportError:
        try:
            import fitz as pymupdf  # older releases
        except ImportError:
            return None
    return pymupdf


def _reference_pages(
    path: str, *, allow_self_check: bool = False
) -> tuple[str, list[str]]:
    """Return (extractor name, per-page text) using an independent reader.

    Falling back to the pipeline's own extractor would turn this into a check
    of the code against itself, which is the one thing it exists to avoid, so
    the fallback has to be asked for and is labelled in the output.
    """
    pymupdf = _independent_reader()

    if pymupdf is not None:
        document = pymupdf.open(path)
        pages = [page.get_text() for page in document]
        return "PyMuPDF (independent)", [" ".join(text.split()) for text in pages]

    if not allow_self_check:
        raise NoIndependentReader(SELF_CHECK_REFUSED)

    document = extract_document(path)
    pages = [page.text for page in document.pages]
    return "pypdf (NOT independent - self check)", [
        " ".join(text.split()) for text in pages
    ]


def _windows(text: str) -> list[str]:
    normalised = " ".join(text.split())
    return [
        normalised[int(len(normalised) * fraction) :][:WINDOW]
        for fraction in FRACTIONS
    ]


def _ingest(db, path: Path, index: int) -> tuple[str, str]:
    sha256, byte_size = file_identity(path)
    file_record = FileRecord(
        root_id=_scratch_root(db),
        relative_path=f"scratch/{index}.pdf",
        name=path.name,
        presence_status=FilePresence.PRESENT.value,
    )
    db.add(file_record)
    db.flush()

    version = FileVersion(
        file_id=file_record.id,
        content_sha256=sha256,
        byte_size=byte_size,
        status="discovered",
    )
    db.add(version)
    db.commit()

    handle_extract_file(db, version.id, path)
    file_record.current_version_id = version.id
    db.commit()
    return version.id, sha256


_ROOT_ID: str | None = None


def _scratch_root(db) -> str:
    global _ROOT_ID
    if _ROOT_ID is None:
        root = AuthorizedRoot(
            mount_id=SCRATCH_MOUNT_ID,
            relative_path="scratch",
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        db.flush()
        _ROOT_ID = root.id
    return _ROOT_ID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="PDF files to verify")
    parser.add_argument("--per-file", type=int, default=3, help="chunks per file")
    parser.add_argument(
        "--allow-self-check",
        action="store_true",
        help="run even without a second reader, and label the result as not independent",
    )
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as db:
        for stale in (
            db.execute(
                select(AuthorizedRoot).where(AuthorizedRoot.mount_id == SCRATCH_MOUNT_ID)
            )
            .scalars()
            .all()
        ):
            db.delete(stale)
        db.commit()

        extractor = None
        rows: list[tuple[str, int, str, str, bool]] = []
        for index, name in enumerate(args.pdfs):
            path = Path(name)
            version_id, content_sha256 = _ingest(db, path, index)
            try:
                reference_extractor, reference_pages = _reference_pages(
                    str(path), allow_self_check=args.allow_self_check
                )
            except NoIndependentReader as exc:
                print(f"refused: {exc}")
                return 2
            extractor = reference_extractor

            chunks = (
                db.execute(
                    select(SourceChunk)
                    .where(SourceChunk.version_id == version_id)
                    .order_by(SourceChunk.ordinal)
                )
                .scalars()
                .all()
            )
            step = max(1, len(chunks) // args.per_file)
            for chunk in chunks[::step][: args.per_file]:
                page = reference_pages[chunk.page_number - 1]
                hit = all(window and window in page for window in _windows(chunk.text))
                rows.append(
                    (
                        path.name,
                        chunk.page_number,
                        chunk.version_id,
                        content_sha256,
                        hit,
                    )
                )

        print(f"reference extractor: {extractor}")
        print("content hash = sha256 of the exact bytes the passage was read from")
        print()
        print(f"{'#':<4}{'file':<40}{'page':<6}{'version':<10}{'content':<10}result")
        print("-" * 82)
        for position, (name, page_number, version_id, sha256, hit) in enumerate(
            rows, start=1
        ):
            print(
                f"{position:<4}{name[:38]:<40}{page_number:<6}{version_id[:8]:<10}"
                f"{sha256[:8]:<10}{'AGREES' if hit else 'MISMATCH'}"
            )

        passed = sum(1 for row in rows if row[4])
        print()
        print(f"page attribution: {passed}/{len(rows)} agree")
        return 0 if passed == len(rows) and rows else 1


if __name__ == "__main__":
    sys.exit(main())
