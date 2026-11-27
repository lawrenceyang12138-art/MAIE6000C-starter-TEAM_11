"""Bounded DOCX body-text extraction using the OOXML package directly."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from services.parsing.chunking import clean_page_text
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
from services.parsing.text import TEXT_MAX_BYTES, TextParsingPolicy

REASON_DOCX_CORRUPT = "docx_corrupt"
REASON_DOCX_STRUCTURE = "docx_structure"
REASON_DOCX_TOO_LARGE = "docx_too_large"
REASON_DOCX_UNPACKED_TOO_LARGE = "docx_unpacked_too_large"

DOCX_MAX_UNPACKED_BYTES = 16 * 1024 * 1024
DOCX_EXTENSIONS = frozenset({".docx"})

_CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_WORDPROCESSING = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCUMENT = f"{{{_WORDPROCESSING}}}document"
_BODY = f"{{{_WORDPROCESSING}}}body"
_PARAGRAPH = f"{{{_WORDPROCESSING}}}p"
_TEXT = f"{{{_WORDPROCESSING}}}t"
_TAB = f"{{{_WORDPROCESSING}}}tab"
_BREAK = f"{{{_WORDPROCESSING}}}br"


def is_docx_path(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in DOCX_EXTENSIONS


def _missing_or_unreadable(path: Path, exc: OSError) -> SourceMissing:
    if isinstance(exc, (FileNotFoundError, IsADirectoryError)):
        return SourceMissing(REASON_FILE_MISSING, f"No such file: {path}")
    return SourceMissing(REASON_UNREADABLE, f"Cannot read DOCX file: {path}")


def _validate_content_types(data: bytes) -> None:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX content types XML is malformed"
        ) from exc
    if root.tag != f"{_CONTENT_TYPES}Types":
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX content types root is invalid"
        )
    for item in root:
        if (
            item.tag == f"{_CONTENT_TYPES}Override"
            and item.get("PartName") == "/word/document.xml"
            and item.get("ContentType", "").endswith(
                "wordprocessingml.document.main+xml"
            )
        ):
            return
    raise UnsupportedDocument(
        REASON_DOCX_STRUCTURE, "DOCX does not declare word/document.xml"
    )


def _validate_package_relationships(data: bytes) -> None:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX package relationships XML is malformed"
        ) from exc
    if root.tag != f"{_RELATIONSHIPS}Relationships":
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX package relationships root is invalid"
        )
    for item in root:
        if (
            item.tag == f"{_RELATIONSHIPS}Relationship"
            and item.get("Type", "").endswith("/officeDocument")
            and item.get("Target", "").lstrip("/") == "word/document.xml"
        ):
            return
    raise UnsupportedDocument(
        REASON_DOCX_STRUCTURE, "DOCX does not point to word/document.xml"
    )


def _body_text(document_xml: bytes) -> str:
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocument(
            REASON_DOCX_CORRUPT, "DOCX document XML is malformed"
        ) from exc
    if root.tag != _DOCUMENT:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX document root is invalid"
        )
    body = root.find(_BODY)
    if body is None:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX document has no body"
        )

    paragraphs: list[str] = []
    for paragraph in body.iter(_PARAGRAPH):
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == _TEXT and node.text:
                pieces.append(node.text)
            elif node.tag == _TAB:
                pieces.append("\t")
            elif node.tag == _BREAK:
                pieces.append("\n")
        paragraphs.append("".join(pieces))
    return "\n".join(paragraphs)


def extract_docx_document(
    path: str | Path,
    policy: TextParsingPolicy,
) -> ExtractedDocument:
    """Extract paragraphs from one DOCX without unpacking to disk."""
    source_path = Path(path)
    limit = min(policy.max_bytes, TEXT_MAX_BYTES)
    try:
        if source_path.stat().st_size > limit:
            raise UnsupportedDocument(
                REASON_DOCX_TOO_LARGE,
                f"DOCX container exceeds the {limit} byte limit",
            )
    except UnsupportedDocument:
        raise
    except OSError as exc:
        raise _missing_or_unreadable(source_path, exc) from exc

    content_sha256, byte_size = file_identity(source_path)
    if byte_size > limit:
        raise UnsupportedDocument(
            REASON_DOCX_TOO_LARGE,
            f"DOCX container exceeds the {limit} byte limit",
        )
    try:
        with source_path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise _missing_or_unreadable(source_path, exc) from exc
    if len(raw) > limit:
        raise UnsupportedDocument(
            REASON_DOCX_TOO_LARGE,
            f"DOCX container exceeds the {limit} byte limit",
        )

    after_sha256, after_size = file_identity(source_path)
    if after_sha256 != content_sha256 or after_size != byte_size:
        raise SourceChanged(
            "source_changed", "The DOCX file was written while it was being read"
        )

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if any(item.flag_bits & 0x1 for item in infos):
                raise UnsupportedDocument(REASON_DOCX_CORRUPT, "DOCX is encrypted")
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
                raise UnsupportedDocument(
                    REASON_DOCX_STRUCTURE,
                    "DOCX is missing required OOXML parts",
                )
            unpacked = sum(item.file_size for item in infos)
            if unpacked > DOCX_MAX_UNPACKED_BYTES:
                raise UnsupportedDocument(
                    REASON_DOCX_UNPACKED_TOO_LARGE,
                    "DOCX uncompressed size exceeds the safety limit",
                )
            _validate_content_types(archive.read("[Content_Types].xml"))
            _validate_package_relationships(archive.read("_rels/.rels"))
            document_xml = archive.read("word/document.xml")
    except UnsupportedDocument:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise UnsupportedDocument(
            REASON_DOCX_CORRUPT, "DOCX package is damaged"
        ) from exc

    text = clean_page_text(_body_text(document_xml))
    if not text:
        raise UnsupportedDocument("empty_text", "DOCX contains no body text")
    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=byte_size,
        page_count=1,
        pages=(PageText(page_number=None, text=text),),
        source_kind="docx",
    )
