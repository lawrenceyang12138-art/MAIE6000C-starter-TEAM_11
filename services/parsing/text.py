"""Strict UTF-8 text and Markdown extraction.

Text files are deliberately treated as plain text. Markdown is not rendered,
HTML is not executed, and no external resource is loaded.

The feature is off by default so existing PDF-only deployments keep their
previous behaviour. A can enable it with ``TEXT_PARSING_ENABLED=true`` or pass
an explicit ``TextParsingPolicy`` from its settings layer. The initial size
limit is 2 MiB.
"""

from __future__ import annotations

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
    SourceChanged,
    SourceMissing,
    UnsupportedDocument,
    file_identity,
)

REASON_TEXT_EMPTY = "empty_text"
REASON_TEXT_ENCODING = "invalid_encoding"
REASON_TEXT_BINARY = "binary_file"
REASON_TEXT_TOO_LARGE = "text_too_large"

TEXT_MAX_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = frozenset({".txt", ".md"})
_DISALLOWED_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class TextParsingPolicy:
    """The part of A's configuration that affects text extraction."""

    enabled: bool = False
    max_bytes: int = TEXT_MAX_BYTES

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "TextParsingPolicy":
        values = os.environ if environ is None else environ
        enabled = _as_bool(
            values.get("TEXT_PARSING_ENABLED", values.get("PARSING_TEXT_ENABLED", "false"))
        )
        raw_limit = values.get("TEXT_MAX_BYTES", str(TEXT_MAX_BYTES))
        try:
            max_bytes = int(raw_limit)
        except ValueError:
            max_bytes = TEXT_MAX_BYTES
        if max_bytes < 1:
            max_bytes = TEXT_MAX_BYTES
        max_bytes = min(max_bytes, TEXT_MAX_BYTES)
        return cls(enabled=enabled, max_bytes=max_bytes)


def _as_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def is_text_path(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in TEXT_EXTENSIONS


def extract_text_document(
    path: str | Path,
    policy: TextParsingPolicy,
) -> ExtractedDocument:
    """Read one TXT/MD file as strict UTF-8 plain text."""
    source_path = Path(path)
    try:
        stat_size = source_path.stat().st_size
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise SourceMissing(REASON_FILE_MISSING, f"No such file: {source_path}") from exc
    except OSError as exc:
        raise SourceMissing(REASON_UNREADABLE, f"Cannot read text file: {source_path}") from exc
    limit = min(policy.max_bytes, TEXT_MAX_BYTES)
    if stat_size > limit:
        raise UnsupportedDocument(
            REASON_TEXT_TOO_LARGE,
            f"Text file exceeds the {limit} byte limit",
        )
    content_sha256, byte_size = file_identity(source_path)

    # Hash the bytes before decoding. The second identity check below closes
    # the same write-during-read window as the PDF extractor.
    if byte_size > limit:
        raise UnsupportedDocument(
            REASON_TEXT_TOO_LARGE,
            f"Text file exceeds the {limit} byte limit",
        )
    try:
        with source_path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, IsADirectoryError)):
            raise SourceMissing(
                "file_missing", f"Text file disappeared while being read: {source_path}"
            ) from exc
        raise SourceMissing(REASON_UNREADABLE, f"Cannot read text file: {source_path}") from exc

    after_sha256, after_size = file_identity(source_path)
    if after_sha256 != content_sha256 or after_size != byte_size:
        raise SourceChanged(
            "source_changed",
            "The text file was written while it was being read",
        )
    if len(raw) > limit:
        raise UnsupportedDocument(
            REASON_TEXT_TOO_LARGE,
            f"Text file exceeds the {limit} byte limit",
        )

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

    source_kind = "markdown" if source_path.suffix.casefold() == ".md" else "text"
    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=byte_size,
        page_count=1,
        pages=(PageText(page_number=None, text=normalized),),
        source_kind=source_kind,
    )
