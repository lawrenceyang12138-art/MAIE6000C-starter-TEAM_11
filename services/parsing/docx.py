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
    SourceSnapshot,
    UnsupportedDocument,
    read_source_snapshot,
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
_WORDPROCESSING_NAMESPACES = frozenset({
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
})
_MATH_NAMESPACES = frozenset({
    "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "http://purl.oclc.org/ooxml/officeDocument/math",
})
_FRACTIONS = {f"{{{ns}}}f" for ns in _MATH_NAMESPACES}
_MARKUP_COMPATIBILITY = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_ALTERNATE_CONTENT = f"{_MARKUP_COMPATIBILITY}AlternateContent"
_ALTERNATE_CHOICE = f"{_MARKUP_COMPATIBILITY}Choice"
_ALTERNATE_FALLBACK = f"{_MARKUP_COMPATIBILITY}Fallback"
_SUPPORTED_ALTERNATE_NAMESPACES = _WORDPROCESSING_NAMESPACES | _MATH_NAMESPACES
_PARAGRAPHS = frozenset(f"{{{namespace}}}p" for namespace in _WORDPROCESSING_NAMESPACES)
_TEXT = {
    f"{{{namespace}}}t"
    for namespace in _WORDPROCESSING_NAMESPACES | _MATH_NAMESPACES
}
_RUN_LAYOUT = {
    f"{{{namespace}}}{name}": separator
    for namespace in _WORDPROCESSING_NAMESPACES
    for name, separator in (("tab", "\t"), ("br", "\n"), ("cr", "\n"))
}
_SKIP_SUBTREES = {
    f"{{{namespace}}}{name}"
    for namespace in _WORDPROCESSING_NAMESPACES
    for name in ("txbxContent", "pPr", "rPr", "rt", "del")
}


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


def _iter_selected_elements(
    node: ElementTree.Element,
    supported_choices: set[ElementTree.Element],
    *,
    stop_at: frozenset[str] = frozenset(),
) -> Iterator[ElementTree.Element]:
    """Walk a document-order view, selecting at most one MC alternate branch."""
    levels = [iter(node)]
    while levels:
        child = next(levels[-1], None)
        if child is None:
            levels.pop()
            continue
        if child.tag in _SKIP_SUBTREES:
            continue
        if child.tag == _ALTERNATE_CONTENT:
            branch = _select_alternate_branch(child, supported_choices)
            if branch is not None:
                levels.append(iter(branch))
            continue
        yield child
        if child.tag not in stop_at:
            levels.append(iter(child))


def _select_alternate_branch(
    node: ElementTree.Element,
    supported_choices: set[ElementTree.Element],
) -> ElementTree.Element | None:
    """Use the first supported choice, or exactly one fallback branch."""
    fallback = None
    for child in node:
        if child in supported_choices:
            return child
        if child.tag == _ALTERNATE_FALLBACK:
            fallback = child
    return fallback


def _mark_fraction_boundaries(fraction: ElementTree.Element) -> None:
    """Insert linear-text delimiters before the ordinary visible-run walk.

    Child fractions are visited first. Parenthesize compound operands so a
    nested fraction or an expression does not change meaning when flattened.
    """
    ns = fraction.tag.removesuffix("f")  # Clark namespace prefix, including the closing brace
    numerator, denominator = fraction.find(ns + "num"), fraction.find(ns + "den")
    if numerator is None or denominator is None:
        return

    def marker(text: str) -> ElementTree.Element:
        token = ElementTree.Element(ns + "t")
        token.text = text
        return token

    for operand in (numerator, denominator):
        simple = (
            len(operand) == 1 and operand[0].tag == ns + "r"
            and "".join(t.text or "" for t in operand[0] if t.tag in _TEXT).isalnum()
        )
        if not simple:
            operand.insert(0, marker("("))
            operand.append(marker(")"))
    kind = fraction.find(f"{ns}fPr/{ns}type")
    # A barless stack (e.g. a binomial) is not a division.
    barless = kind is not None and kind.get(ns + "val") == "noBar"
    denominator.insert(0, marker(" " if barless else "/"))


def _parse_document_xml(
    data: bytes,
) -> tuple[ElementTree.Element, set[ElementTree.Element]]:
    """Resolve MC Requires prefixes in scope, retaining only supported choices."""
    namespaces: dict[str, str] = {}
    supported_choices: set[ElementTree.Element] = set()
    pending: list[tuple[str, str | None]] = []
    scope_stack: list[list[tuple[str, str | None]]] = []
    events = ElementTree.iterparse(
        io.BytesIO(data), events=("start", "end", "start-ns")
    )
    for event, value in events:
        if event == "start-ns":
            prefix, uri = value
            pending.append((prefix, namespaces.get(prefix)))
            namespaces[prefix] = uri
        elif event == "start":
            scope_stack.append(pending)
            pending = []
            if value.tag == _ALTERNATE_CHOICE:
                requirements = value.get("Requires", "").split()
                if requirements and all(
                    namespaces.get(prefix) in _SUPPORTED_ALTERNATE_NAMESPACES
                    for prefix in requirements
                ):
                    supported_choices.add(value)
        else:
            if value.tag in _FRACTIONS:
                _mark_fraction_boundaries(value)
            # Undo only the declarations introduced on this element. This
            # also restores prefixes shadowed by a different local binding.
            for prefix, previous in reversed(scope_stack.pop()):
                if previous is None:
                    namespaces.pop(prefix)
                else:
                    namespaces[prefix] = previous
    return events.root, supported_choices


def _paragraph_text(
    paragraph: ElementTree.Element,
    supported_choices: set[ElementTree.Element],
) -> str:
    pieces: list[str] = []
    for node in _iter_selected_elements(paragraph, supported_choices):
        if node.tag in _TEXT and node.text:
            pieces.append(node.text)
        elif node.tag in _RUN_LAYOUT:
            pieces.append(_RUN_LAYOUT[node.tag])
    return "".join(pieces)


def _body_text(document_xml: bytes) -> str:
    try:
        root, supported_choices = _parse_document_xml(document_xml)
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
        _paragraph_text(paragraph, supported_choices)
        for paragraph in _iter_selected_elements(body, supported_choices, stop_at=_PARAGRAPHS)
        if paragraph.tag in _PARAGRAPHS
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
    *,
    snapshot: SourceSnapshot | None = None,
) -> ExtractedDocument:
    """Extract paragraphs from one DOCX without unpacking to disk."""
    limit = min(policy.max_bytes, TEXT_MAX_BYTES)
    if snapshot is None:
        snapshot = read_source_snapshot(Path(path), native_limit=limit, keep_pdf=False)
    content_sha256 = snapshot.content_sha256
    raw = snapshot.native_bytes(
        limit, REASON_DOCX_TOO_LARGE, f"DOCX container exceeds the {limit} byte limit",
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
