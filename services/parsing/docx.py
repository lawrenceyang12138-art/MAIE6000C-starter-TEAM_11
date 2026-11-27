"""Bounded DOCX body-text extraction using the OOXML package directly."""

from __future__ import annotations

import io
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from services.parsing.pdf import (
    ExtractedDocument,
    PageText,
    UnsupportedDocument,
)
from services.parsing.text import TEXT_MAX_BYTES, TextParsingPolicy, read_native_source

REASON_DOCX_CORRUPT = "docx_corrupt"
REASON_DOCX_STRUCTURE = "docx_structure"
REASON_DOCX_TOO_LARGE = "docx_too_large"
REASON_DOCX_UNPACKED_TOO_LARGE = "docx_unpacked_too_large"

DOCX_MAX_UNPACKED_BYTES = 16 * 1024 * 1024
DOCX_EXTENSIONS = frozenset({".docx"})

_CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_WORDPROCESSING_NAMESPACES = frozenset({
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
})


def is_docx_path(path: str | Path) -> bool:
    return Path(path).suffix.casefold() in DOCX_EXTENSIONS


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


def _iter_word_elements(
    node: ElementTree.Element, tag: str, *, skip: str
) -> Iterator[ElementTree.Element]:
    """Yield matches in document order without descending into them or text boxes."""
    levels = [iter(node)]
    while levels:
        child = next(levels[-1], None)
        if child is None:
            levels.pop()
        elif child.tag == skip:
            continue
        elif child.tag == tag:
            yield child
        else:
            levels.append(iter(child))


def _paragraph_text(paragraph: ElementTree.Element, prefix: str) -> str:
    pieces: list[str] = []
    text_tag = f"{prefix}t"
    tab_tag = f"{prefix}tab"
    breaks = {f"{prefix}br", f"{prefix}cr"}
    for run in _iter_word_elements(paragraph, f"{prefix}r", skip=f"{prefix}txbxContent"):
        # Only direct run content is visible: w:pPr/w:tabs/w:tab is a
        # paragraph tab stop, not a character in the passage.
        for child in run:
            if child.tag == text_tag and child.text:
                pieces.append(child.text)
            elif child.tag == tab_tag:
                pieces.append("\t")
            elif child.tag in breaks:
                pieces.append("\n")
    return "".join(pieces)


def _body_text(document_xml: bytes) -> str:
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise UnsupportedDocument(
            REASON_DOCX_CORRUPT, "DOCX document XML is malformed"
        ) from exc
    namespace, _, name = root.tag.rpartition("}")
    if name != "document" or namespace[1:] not in _WORDPROCESSING_NAMESPACES:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX document root is invalid"
        )
    prefix = namespace + "}"
    body = root.find(f"{prefix}body")
    if body is None:
        raise UnsupportedDocument(
            REASON_DOCX_STRUCTURE, "DOCX document has no body"
        )

    paragraphs = (
        _paragraph_text(paragraph, prefix)
        for paragraph in _iter_word_elements(body, f"{prefix}p", skip=f"{prefix}txbxContent")
    )
    return "\n".join(paragraphs)


def _decode_docx(raw: bytes) -> str:
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
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, zlib.error) as exc:
        raise UnsupportedDocument(
            REASON_DOCX_CORRUPT, "DOCX package is damaged"
        ) from exc

    text = _body_text(document_xml).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise UnsupportedDocument("empty_text", "DOCX contains no body text")
    return text


def extract_docx_document(
    path: str | Path,
    policy: TextParsingPolicy,
) -> ExtractedDocument:
    """Extract paragraphs from one DOCX without unpacking to disk."""
    limit = min(policy.max_bytes, TEXT_MAX_BYTES)
    raw, content_sha256 = read_native_source(
        Path(path),
        max_bytes=limit,
        too_large_code=REASON_DOCX_TOO_LARGE,
        too_large_message=f"DOCX container exceeds the {limit} byte limit",
    )
    try:
        text = _decode_docx(raw)
    except UnsupportedDocument as exc:
        exc.content_sha256 = content_sha256
        raise
    return ExtractedDocument(
        content_sha256=content_sha256,
        byte_size=len(raw),
        page_count=1,
        pages=(PageText(page_number=None, text=text),),
        source_kind="docx",
    )
