"""Strict UTF-8 text and Markdown extraction.

Text files are deliberately treated as plain text. Markdown is not rendered,
HTML is not executed, and no external resource is loaded.

TXT/Markdown and DOCX have separate switches. Both are off by default so
existing PDF-only deployments keep their previous behaviour. A can enable
plain text with ``TEXT_PARSING_ENABLED=true`` and DOCX independently with
``DOCX_PARSING_ENABLED=true``, or pass an explicit ``TextParsingPolicy`` from
its settings layer. The initial size limit is 2 MiB.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from services.parsing.pdf import (
    REASON_FILE_MISSING,
    REASON_UNREADABLE,
    ExtractedDocument,
    PageText,
    SourceMissing,
    UnsupportedDocument,
)

REASON_TEXT_EMPTY = "empty_text"
REASON_TEXT_ENCODING = "invalid_encoding"
REASON_TEXT_BINARY = "binary_file"
REASON_TEXT_TOO_LARGE = "text_too_large"

TEXT_MAX_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = frozenset({".txt", ".md"})
_DISALLOWED_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HASH_BLOCK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class TextParsingPolicy:
    """The part of A's configuration that affects text extraction."""

    enabled: bool = False
    docx_enabled: bool = False
    max_bytes: int = TEXT_MAX_BYTES

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "TextParsingPolicy":
        values = os.environ if environ is None else environ
        enabled = _as_bool(
            values.get("TEXT_PARSING_ENABLED", values.get("PARSING_TEXT_ENABLED", "false"))
        )
        docx_enabled = _as_bool(values.get("DOCX_PARSING_ENABLED", "false"))
        raw_limit = values.get("TEXT_MAX_BYTES", str(TEXT_MAX_BYTES))
        try:
            max_bytes = int(raw_limit)
        except ValueError:
            max_bytes = TEXT_MAX_BYTES
        if max_bytes < 1:
            max_bytes = TEXT_MAX_BYTES
        max_bytes = min(max_bytes, TEXT_MAX_BYTES)
        return cls(enabled=enabled, docx_enabled=docx_enabled, max_bytes=max_bytes)


def _as_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def is_text_path(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in TEXT_EXTENSIONS


def read_native_source(
    path: Path, *, max_bytes: int, too_large_code: str, too_large_message: str
) -> tuple[bytes, str]:
    """Return a bounded snapshot and the hash of exactly those bytes."""
    try:
        with path.open("rb") as stream:
            # Explicit policies can bypass environment validation; never pass
            # a negative size to read(), which would read without a limit.
            raw = stream.read(max(0, max_bytes + 1))
            digest = hashlib.sha256(raw)
            if len(raw) > max_bytes:
                # Do not parse or buffer the rest of an oversized file. Hash
                # it in blocks so this rejection describes the full snapshot,
                # not a prefix that cannot be compared with the scanned hash.
                while block := stream.read(_HASH_BLOCK_SIZE):
                    digest.update(block)
                raise UnsupportedDocument(
                    too_large_code, too_large_message, content_sha256=digest.hexdigest()
                )
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise SourceMissing(REASON_FILE_MISSING, f"No such file: {path}") from exc
    except OSError as exc:
        raise SourceMissing(REASON_UNREADABLE, f"Cannot read file: {path}") from exc
    return raw, digest.hexdigest()


def _decode_text(raw: bytes) -> str:
    try:
        # utf-8-sig accepts a leading BOM and is strict for every other byte.
        decoded = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocument(
            REASON_TEXT_ENCODING,
            "Text file is not valid UTF-8",
        ) from exc

    if _DISALLOWED_CONTROL.search(decoded):
        raise UnsupportedDocument(
            REASON_TEXT_BINARY,
            "Text file contains binary control bytes",
        )

    # Both LF and CRLF become one stable internal representation.
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise UnsupportedDocument(REASON_TEXT_EMPTY, "Text file is empty")
    return normalized


def extract_text_document(
    path: str | Path,
    policy: TextParsingPolicy,
) -> ExtractedDocument:
    """Read one TXT/MD file as strict UTF-8 plain text."""
    source_path = Path(path)
    limit = min(policy.max_bytes, TEXT_MAX_BYTES)
    raw, content_sha256 = read_native_source(
        source_path,
        max_bytes=limit,
        too_large_code=REASON_TEXT_TOO_LARGE,
        too_large_message=f"Text file exceeds the {limit} byte limit",
    )
    try:
        normalized = _decode_text(raw)
    except UnsupportedDocument as exc:
        exc.content_sha256 = content_sha256
        raise
    source_kind = "markdown" if source_path.suffix.casefold() == ".md" else "text"
    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=len(raw),
        page_count=1,
        pages=(PageText(page_number=None, text=normalized),),
        source_kind=source_kind,
    )
