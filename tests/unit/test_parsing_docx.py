"""DOCX extraction validates the OOXML package before reading body text."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import Relationship, SourceChunk, VersionStatus
from services.parsing.handler import handle_extract_file
from services.parsing.docx import (
    REASON_DOCX_CORRUPT,
    REASON_DOCX_STRUCTURE,
    REASON_DOCX_UNPACKED_TOO_LARGE,
)
from services.parsing.pdf import UnsupportedDocument, extract_document
from services.parsing.text import TextParsingPolicy

POLICY = TextParsingPolicy(enabled=True, docx_enabled=True)

CONTENT_TYPES = b"""\
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
RELATIONSHIPS = b"""\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
"""


def _document(body: str) -> bytes:
    return f"""\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>
""".encode()


def _write_docx(path: Path, body: str, *, content_types=CONTENT_TYPES,
                relationships=RELATIONSHIPS) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if content_types is not None:
            archive.writestr("[Content_Types].xml", content_types)
        if relationships is not None:
            archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", _document(body))
    return path


def _reason(path: Path) -> str:
    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(path, text_policy=POLICY)
    return excinfo.value.reason_code


def test_docx_extracts_paragraph_text_without_pages(tmp_path):
    path = _write_docx(
        tmp_path / "notes.docx",
        "<w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>",
    )

    document = extract_document(path, text_policy=POLICY)

    assert document.source_kind == "docx"
    assert document.page_count == 1
    assert document.pages[0].page_number is None
    assert document.pages[0].text == "First paragraph\nSecond paragraph"


def test_missing_ooxml_declarations_are_rejected(tmp_path):
    path = _write_docx(
        tmp_path / "missing-parts.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
        content_types=None,
    )

    assert _reason(path) == REASON_DOCX_STRUCTURE


def test_bad_package_relationships_are_rejected(tmp_path):
    path = _write_docx(
        tmp_path / "bad-relationships.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
        relationships=b"<Relationships/>",
    )

    assert _reason(path) == REASON_DOCX_STRUCTURE


def test_corrupt_zip_is_reported_as_corrupt(tmp_path):
    path = tmp_path / "damaged.docx"
    path.write_bytes(b"not a zip package")

    assert _reason(path) == REASON_DOCX_CORRUPT


def test_uncompressed_size_limit_is_enforced(tmp_path, monkeypatch):
    import services.parsing.docx as docx_module

    monkeypatch.setattr(docx_module, "DOCX_MAX_UNPACKED_BYTES", 1024)
    path = _write_docx(
        tmp_path / "large-unpacked.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
    )
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/extra.bin", b"x" * 4096)

    assert _reason(path) == REASON_DOCX_UNPACKED_TOO_LARGE


def test_docx_without_body_text_is_an_explicit_empty_result(tmp_path):
    path = _write_docx(tmp_path / "empty.docx", "<w:p/>")

    assert _reason(path) == "empty_text"


def test_docx_has_its_own_switch(tmp_path):
    path = _write_docx(
        tmp_path / "disabled.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
    )

    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(
            path,
            text_policy=TextParsingPolicy(enabled=True, docx_enabled=False),
        )

    assert excinfo.value.reason_code == "unsupported_format"


def test_docx_environment_switch_is_independent(tmp_path, monkeypatch):
    path = _write_docx(
        tmp_path / "environment.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
    )
    monkeypatch.delenv("TEXT_PARSING_ENABLED", raising=False)
    monkeypatch.delenv("PARSING_TEXT_ENABLED", raising=False)
    monkeypatch.setenv("DOCX_PARSING_ENABLED", "true")

    document = extract_document(path)

    assert document.source_kind == "docx"


def test_docx_handler_uses_null_pages_and_skips_relations(
    db_session: Session, make_file_version, tmp_path
):
    path = _write_docx(
        tmp_path / "body.docx",
        "<w:p><w:r><w:t>DOCX evidence passage</w:t></w:r></w:p>",
    )
    version_id = make_file_version(source_path=path)

    assert (
        handle_extract_file(
            db_session,
            version_id,
            path,
            text_policy=POLICY,
        )
        == VersionStatus.BASIC_READY.value
    )
    chunks = (
        db_session.execute(
            select(SourceChunk).where(SourceChunk.version_id == version_id)
        )
        .scalars()
        .all()
    )
    assert chunks and all(chunk.page_number is None for chunk in chunks)
    assert (
        db_session.execute(
            select(Relationship).where(Relationship.source_version_id == version_id)
        )
        .scalars()
        .all()
        == []
    )

