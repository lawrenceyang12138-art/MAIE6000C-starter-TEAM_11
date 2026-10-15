"""Per-page text extraction from text-based PDFs.

The goal is not "read the PDF". It is to produce located text: every page of
text keeps the page number a reader would see in a PDF viewer, and every
document carries the identity of the exact bytes that were read. Without that,
search results cannot point at "page 7" and old evidence cannot be told apart
from current evidence.

Failures are reported as explicit reason codes rather than exceptions that
stop a whole scan. An encrypted, damaged, or image-only document is a normal
outcome here, not a crash.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

# Reason codes are stable strings: they end up in the database and in the UI,
# so they must not change casually.
REASON_ENCRYPTED = "encrypted"
REASON_CORRUPT = "corrupt"
REASON_NO_TEXT_LAYER = "no_text_layer"
REASON_UNREADABLE = "unreadable"

_CHUNK_SIZE = 1024 * 1024


class UnsupportedDocument(Exception):
    """A document we cannot turn into text, with a reason we can show.

    Callers should record ``reason_code`` against the file version and move on
    to the next file.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


@dataclass(frozen=True)
class PageText:
    """The text of one page, with the 1-based page number a reader sees."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    """A parsed document plus the identity of the bytes it came from."""

    content_sha256: str
    byte_size: int
    page_count: int
    pages: tuple[PageText, ...]


def file_identity(path: Path) -> tuple[str, int]:
    """Return (sha256, byte size) for a file, read in bounded chunks.

    The hash is what lets us say "this text came from these exact bytes" and
    detect that a file changed underneath us.
    """
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(_CHUNK_SIZE)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


def _read_pages(path: Path) -> list[str]:
    """Return the raw extracted text of each page in document order."""
    try:
        reader = PdfReader(str(path))
    except FileNotDecryptedError as exc:
        raise UnsupportedDocument(REASON_ENCRYPTED, "PDF is encrypted") from exc
    except PdfReadError as exc:
        raise UnsupportedDocument(REASON_CORRUPT, f"Cannot read PDF: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any reader failure is a bad file
        raise UnsupportedDocument(REASON_UNREADABLE, f"Cannot open PDF: {exc}") from exc

    if reader.is_encrypted:
        # An empty password is the common "owner password only" case, which
        # still lets us read the text. Anything else is a real encryption.
        try:
            if reader.decrypt("") == 0:
                raise UnsupportedDocument(REASON_ENCRYPTED, "PDF is encrypted")
        except UnsupportedDocument:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedDocument(REASON_ENCRYPTED, "PDF is encrypted") from exc

    pages: list[str] = []
    try:
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as exc:  # noqa: BLE001 - damaged page objects
        raise UnsupportedDocument(REASON_CORRUPT, f"Cannot read page: {exc}") from exc
    return pages


def extract_document(path: str | Path) -> ExtractedDocument:
    """Extract per-page text and the file identity from one PDF.

    Raises UnsupportedDocument when the file cannot yield text. A file that
    opens but contains no extractable text at all (a scan with no text layer)
    is also unsupported: reporting "0 chunks" would look like an empty
    document rather than a missing text layer.
    """
    pdf_path = Path(path)
    content_sha256, byte_size = file_identity(pdf_path)

    raw_pages = _read_pages(pdf_path)
    pages = tuple(
        PageText(page_number=index, text=text)
        for index, text in enumerate(raw_pages, start=1)
    )

    if not pages:
        raise UnsupportedDocument(REASON_CORRUPT, "PDF has no pages")

    if not any(page.text.strip() for page in pages):
        raise UnsupportedDocument(
            REASON_NO_TEXT_LAYER,
            "PDF has no extractable text (likely a scan without OCR)",
        )

    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=byte_size,
        page_count=len(pages),
        pages=pages,
    )
