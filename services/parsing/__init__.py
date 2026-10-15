"""Document parsing and chunking for the file management assistant.

This package is owned by the "read files" workstream. It turns a file on disk
into located pieces of text that the rest of the system can index and cite.
"""

from services.parsing.pdf import (
    ExtractedDocument,
    PageText,
    UnsupportedDocument,
    extract_document,
    file_identity,
)
from services.parsing.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    MIN_CHUNK_CHARS,
    Chunk,
    chunk_document,
    clean_page_text,
    strip_running_headers_footers,
)
from services.parsing.persist import InvalidChunkSet, persist_chunks
from services.parsing.handler import (
    PARSER_REVISION,
    REASON_SOURCE_CHANGED,
    handle_extract_file,
)
from services.parsing.evidence import (
    REASON_CHUNK_NOT_FOUND,
    REASON_FILE_MISSING,
    REASON_ROOT_REVOKED,
    REASON_VERSION_SUPERSEDED,
    Evidence,
    SourceUnavailable,
    read_evidence,
)

__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "CHUNK_SIZE_CHARS",
    "MIN_CHUNK_CHARS",
    "Chunk",
    "Evidence",
    "ExtractedDocument",
    "InvalidChunkSet",
    "PageText",
    "PARSER_REVISION",
    "REASON_CHUNK_NOT_FOUND",
    "REASON_FILE_MISSING",
    "REASON_ROOT_REVOKED",
    "REASON_SOURCE_CHANGED",
    "REASON_VERSION_SUPERSEDED",
    "SourceUnavailable",
    "UnsupportedDocument",
    "chunk_document",
    "clean_page_text",
    "extract_document",
    "file_identity",
    "handle_extract_file",
    "persist_chunks",
    "read_evidence",
    "strip_running_headers_footers",
]
