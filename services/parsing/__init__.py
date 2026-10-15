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

__all__ = [
    "ExtractedDocument",
    "PageText",
    "UnsupportedDocument",
    "extract_document",
    "file_identity",
]
