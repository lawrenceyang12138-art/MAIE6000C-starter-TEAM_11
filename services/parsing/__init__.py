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

__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "CHUNK_SIZE_CHARS",
    "MIN_CHUNK_CHARS",
    "Chunk",
    "ExtractedDocument",
    "PageText",
    "UnsupportedDocument",
    "chunk_document",
    "clean_page_text",
    "extract_document",
    "file_identity",
    "strip_running_headers_footers",
]
