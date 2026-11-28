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
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

# Reason codes are stable strings: they end up in the database and in the UI,
# so they must not change casually.
REASON_ENCRYPTED = "encrypted"
REASON_CORRUPT = "corrupt"
REASON_NO_TEXT_LAYER = "no_text_layer"
REASON_UNREADABLE = "unreadable"
REASON_UNSUPPORTED_FORMAT = "unsupported_format"
# The path is not there at all. This is not a property of the document - it
# means the file moved or was deleted between the scan and the parse - so it is
# a separate exception rather than another "unsupported document" reason.
REASON_FILE_MISSING = "file_missing"
# The bytes on disk are no longer the bytes this version was created from.
REASON_SOURCE_CHANGED = "source_changed"


class SourceMissing(Exception):
    """The file could not be read because it is no longer at that path."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


class SourceChanged(Exception):
    """The file was written while it was being read."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message

_CHUNK_SIZE = 1024 * 1024
_PDF_MAGIC = b"%PDF-"


class UnsupportedDocument(Exception):
    """A document we cannot turn into text, with a reason we can show.

    Readers also report the hash of the snapshot they rejected, so a
    rejection can be recorded only against the matching file version.
    """

    def __init__(
        self, reason_code: str, message: str, *, content_sha256: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.content_sha256 = content_sha256


@dataclass(frozen=True)
class PageText:
    """The text of one page, with the 1-based page number a reader sees."""

    page_number: int | None
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    """A parsed document plus the identity of the bytes it came from."""

    content_sha256: str
    byte_size: int
    page_count: int
    pages: tuple[PageText, ...]
    source_kind: str = "pdf"


def _source_read_failure(path: Path, exc: OSError) -> SourceMissing:
    if isinstance(exc, FileNotFoundError):
        return SourceMissing(REASON_FILE_MISSING, f"No such file: {path}")
    if isinstance(exc, IsADirectoryError):
        return SourceMissing(REASON_FILE_MISSING, f"Not a file: {path}")
    return SourceMissing(REASON_UNREADABLE, f"Cannot read file: {path}")


def file_identity(path: str | Path) -> tuple[str, int]:
    """Return (sha256, byte size) for a file, read in bounded chunks.

    The hash is what lets us say "this text came from these exact bytes" and
    detect that a file changed underneath us.
    """
    source = read_source_snapshot(Path(path), native_limit=0, keep_pdf=False)
    return source.content_sha256, source.byte_size


@dataclass(frozen=True)
class SourceSnapshot:
    content_sha256: str
    byte_size: int
    data: bytes | None  # None: hashed to EOF but too large to keep.

    def native_bytes(self, limit: int, reason: str, message: str) -> bytes:
        if self.byte_size > limit or self.data is None:
            raise UnsupportedDocument(reason, message, content_sha256=self.content_sha256)
        return self.data


def read_source_snapshot(path: Path, *, native_limit: int, keep_pdf: bool = True) -> SourceSnapshot:
    """Open once. Even when the native size limit is exceeded, hash the entire source."""
    digest = hashlib.sha256()
    size = 0
    saved = BytesIO()
    retain = True
    is_pdf = False
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(_CHUNK_SIZE)
                if not block:
                    break
                if size == 0:
                    is_pdf = keep_pdf and block.startswith(_PDF_MAGIC)
                size += len(block)
                digest.update(block)
                if retain:
                    if is_pdf or size <= native_limit:
                        saved.write(block)
                    else:
                        saved.close()
                        retain = False
    except OSError as exc:
        # External disks and network mounts can fail after open succeeded.
        # Keep those source failures on the same explicit refusal/retry path
        # as an unreadable file instead of leaking an HTTP 500 from evidence.
        raise _source_read_failure(path, exc) from exc
    return SourceSnapshot(digest.hexdigest(), size, saved.getvalue() if retain else None)


def _read_pages(snapshot: BytesIO) -> list[str]:
    """Return the raw extracted text of each page in document order."""
    try:
        reader = PdfReader(snapshot)
    except OSError:
        raise
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
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 - damaged page objects
        raise UnsupportedDocument(REASON_CORRUPT, f"Cannot read page: {exc}") from exc
    return pages


def _source_stamp(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def verify_source(path: str | Path, *, content_sha256: str, byte_size: int) -> None:
    """Verify the named file, including rejected sources above the native size cap."""
    path = Path(path)
    digest = hashlib.sha256()
    remaining = byte_size
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size != byte_size:
                raise SourceChanged(REASON_SOURCE_CHANGED, "The source size changed")
            while remaining:
                block = stream.read(min(remaining, _CHUNK_SIZE))
                if not block:
                    break
                digest.update(block)
                remaining -= len(block)
            after = _source_stamp(os.fstat(stream.fileno()))
        at_path = _source_stamp(path.stat())
    except OSError as exc:
        raise _source_read_failure(path, exc) from exc

    if (
        remaining or digest.hexdigest() != content_sha256
        or _source_stamp(before) != after or after != at_path
    ):
        raise SourceChanged(REASON_SOURCE_CHANGED, "The source changed during extraction")


def _extract_pdf_document(pdf_path: Path, source: SourceSnapshot) -> ExtractedDocument:
    """Extract per-page text and the file identity from one PDF.

    Raises UnsupportedDocument when the file cannot yield text. A file that
    opens but contains no extractable text at all (a scan with no text layer)
    is also unsupported: reporting "0 chunks" would look like an empty
    document rather than a missing text layer.
    """
    content_sha256, byte_size = source.content_sha256, source.byte_size
    with BytesIO(source.data) as snapshot:
        try:
            raw_pages = _read_pages(snapshot)
        except UnsupportedDocument as exc:
            verify_source(pdf_path, content_sha256=content_sha256, byte_size=byte_size)
            exc.content_sha256 = content_sha256
            raise
        except OSError as exc:
            raise _source_read_failure(pdf_path, exc) from exc

    verify_source(pdf_path, content_sha256=content_sha256, byte_size=byte_size)

    pages = tuple(
        PageText(page_number=index, text=text)
        for index, text in enumerate(raw_pages, start=1)
    )

    if not pages:
        raise UnsupportedDocument(REASON_CORRUPT, "PDF has no pages", content_sha256=content_sha256)

    if not any(page.text.strip() for page in pages):
        raise UnsupportedDocument(
            REASON_NO_TEXT_LAYER,
            "PDF has no extractable text (likely a scan without OCR)",
            content_sha256=content_sha256,
        )

    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=byte_size,
        page_count=len(pages),
        pages=pages,
    )


def extract_document(
    path: str | Path,
    *,
    text_policy=None,
) -> ExtractedDocument:
    """Extract a PDF, or an enabled UTF-8 TXT/Markdown file.

    The local import avoids a module cycle while keeping all PDF behaviour in
    this module and all text-specific rules in ``services.parsing.text``.
    """
    from services.parsing.text import TEXT_MAX_BYTES, TextParsingPolicy, is_text_path
    from services.parsing.docx import is_docx_path

    path = Path(path)
    policy = text_policy or TextParsingPolicy.from_environment()
    text = policy.enabled and is_text_path(path)
    docx = policy.docx_enabled and is_docx_path(path)
    limit = min(policy.max_bytes, TEXT_MAX_BYTES) if text or docx else 0
    source = read_source_snapshot(path, native_limit=limit)
    if source.data is not None and source.data.startswith(_PDF_MAGIC):
        return _extract_pdf_document(path, source)
    if text:
        from services.parsing.text import extract_text_document

        return extract_text_document(path, policy, snapshot=source)
    if docx:
        from services.parsing.docx import extract_docx_document

        return extract_docx_document(path, policy, snapshot=source)
    raise UnsupportedDocument(
        REASON_UNSUPPORTED_FORMAT, "Not a PDF file; no native parser enabled for this suffix",
        content_sha256=source.content_sha256,
    )
