"""DOCX extraction validates the OOXML package before reading body text."""

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import FileVersion, Relationship, SourceChunk, VersionStatus
from services.parsing.handler import handle_extract_file
from services.parsing.docx import (
    REASON_DOCX_CORRUPT,
    REASON_DOCX_STRUCTURE,
    REASON_DOCX_UNPACKED_TOO_LARGE,
)
from services.parsing.pdf import REASON_SOURCE_CHANGED, UnsupportedDocument, extract_document
from services.parsing.text import TextParsingPolicy

POLICY = TextParsingPolicy(enabled=True, docx_enabled=True)
TRANSITIONAL_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT_WORD_NAMESPACE = "http://purl.oclc.org/ooxml/wordprocessingml/main"

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


def _document(body: str, namespace: str) -> bytes:
    return f"""\
<w:document xmlns:w="{namespace}">
  <w:body>{body}</w:body>
</w:document>
""".encode()


def _write_docx(
    path: Path,
    body: str,
    *,
    content_types=CONTENT_TYPES,
    relationships=RELATIONSHIPS,
    namespace=TRANSITIONAL_WORD_NAMESPACE,
) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if content_types is not None:
            archive.writestr("[Content_Types].xml", content_types)
        if relationships is not None:
            archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", _document(body, namespace))
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


@pytest.mark.parametrize(
    "namespace",
    [TRANSITIONAL_WORD_NAMESPACE, STRICT_WORD_NAMESPACE],
    ids=["transitional", "strict"],
)
def test_docx_preserves_run_layout_but_ignores_paragraph_tab_stops(tmp_path, namespace):
    relationships = RELATIONSHIPS
    if namespace == STRICT_WORD_NAMESPACE:
        relationships = relationships.replace(
            b"http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
            b"http://purl.oclc.org/ooxml/officeDocument/relationships/",
        )
    path = _write_docx(
        tmp_path / "layout.docx",
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        "<w:r><w:t>Before</w:t><w:cr/><w:t>Middle</w:t><w:br/>"
        "<w:tab/><w:t>After</w:t></w:r>"
        '<w:hyperlink w:anchor="bookmark"><w:r><w:t xml:space="preserve"> link</w:t>'
        "</w:r></w:hyperlink></w:p>",
        relationships=relationships,
        namespace=namespace,
    )

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "Before\nMiddle\n\tAfter link"


def test_docx_extracts_office_math_and_ruby_base_not_annotation(tmp_path):
    body = (
        "<w:p><w:r><w:t>Operating </w:t></w:r>"
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        "<m:r><w:t>Margin</w:t><m:t> + 1</m:t></m:r></m:oMath>"
        "<w:r><w:t>; ruby: </w:t></w:r>"
        "<w:r><w:ruby><w:rt><w:r><w:t>kanji</w:t></w:r></w:rt>"
        "<w:rubyBase><w:r><w:t>漢字</w:t></w:r></w:rubyBase></w:ruby></w:r></w:p>"
    )
    path = _write_docx(tmp_path / "math-and-ruby.docx", body)

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "Operating Margin + 1; ruby: 漢字"


@pytest.mark.parametrize(
    ("numerator", "denominator", "kind", "expected"),
    [
        ("a+b", "2", "bar", "(a+b)/2"),
        ("1", "<m:f><m:num><m:r><m:t>2</m:t></m:r></m:num>"
         "<m:den><m:r><m:t>3</m:t></m:r></m:den></m:f>", "lin", "1/(2/3)"),
        ("1", "2", "noBar", "1 2"),
    ],
)
def test_fraction_operands_preserve_grouping(tmp_path, numerator, denominator, kind, expected):
    def operand(value):
        return value if value.startswith("<") else f"<m:r><m:t>{value}</m:t></m:r>"

    body = (
        '<w:p><m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        f'<m:f><m:fPr><m:type m:val="{kind}"/></m:fPr><m:num>{operand(numerator)}</m:num>'
        f'<m:den>{operand(denominator)}</m:den></m:f></m:oMath></w:p>'
    )
    path = _write_docx(tmp_path / "fraction.docx", body)
    assert extract_document(path, text_policy=POLICY).pages[0].text == expected


def test_docx_alternate_content_chooses_one_supported_branch(tmp_path):
    body = (
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
        'markup-compatibility/2006" '
        f'xmlns:alias="{TRANSITIONAL_WORD_NAMESPACE}">'
        '<mc:Choice Requires="alias" xmlns:alias="urn:unsupported-feature">'
        "<w:p><w:r><w:t>Wrong choice</w:t></w:r></w:p></mc:Choice>"
        '<mc:Choice Requires="alias"><w:p><w:r><w:t>Chosen</w:t></w:r></w:p>'
        "</mc:Choice>"
        "<mc:Fallback><w:p><w:r><w:t>Fallback</w:t></w:r></w:p></mc:Fallback>"
        "</mc:AlternateContent>"
    )
    path = _write_docx(tmp_path / "alternate-supported.docx", body)

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "Chosen"
    assert "Fallback" not in document.pages[0].text


def test_docx_alternate_content_falls_back_for_unsupported_requirement(tmp_path):
    body = (
        '<w:p><w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/'
        'markup-compatibility/2006" xmlns:future="urn:unsupported-feature">'
        '<mc:Choice Requires="future"><w:t>Future only</w:t>'
        "</mc:Choice>"
        "<mc:Fallback><w:t>Compatible text</w:t></mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>"
    )
    path = _write_docx(tmp_path / "alternate-fallback.docx", body)

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "Compatible text"
    assert "Future only" not in document.pages[0].text


def test_docx_rejects_unrecognized_word_namespace(tmp_path):
    path = _write_docx(
        tmp_path / "foreign-namespace.docx",
        "<w:p><w:r><w:t>body</w:t></w:r></w:p>",
        namespace="urn:test:lookalike-wordprocessing",
    )

    assert _reason(path) == REASON_DOCX_STRUCTURE


def test_docx_text_box_does_not_interrupt_or_duplicate_body_text(tmp_path):
    body = (
        "<w:p><w:r><w:t>Before</w:t></w:r>"
        "<w:r><w:txbxContent><w:p><w:r><w:t>Sidebar</w:t></w:r></w:p>"
        "</w:txbxContent></w:r><w:r><w:t>After</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Next paragraph</w:t></w:r></w:p>"
    )
    path = _write_docx(tmp_path / "text-box.docx", body)

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "BeforeAfter\nNext paragraph"
    assert "Sidebar" not in document.pages[0].text


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


def test_corrupt_docx_member_is_reported_as_corrupt(tmp_path, monkeypatch):
    path = _write_docx(tmp_path / "damaged-member.docx", "<w:p/>")
    real_read = zipfile.ZipFile.read

    def read_member(archive, name, pwd=None):
        if name == "word/document.xml":
            raise zlib.error("invalid compressed contents")
        return real_read(archive, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", read_member)

    assert _reason(path) == REASON_DOCX_CORRUPT


def test_a_corrupt_replacement_does_not_reject_the_original_version(
    db_session: Session, make_file_version, tmp_path
):
    path = _write_docx(
        tmp_path / "replaced.docx", "<w:p><w:r><w:t>Original passage</w:t></w:r></w:p>"
    )
    version_id = make_file_version(source_path=path)
    path.write_bytes(b"not a zip package")

    status = handle_extract_file(db_session, version_id, path, text_policy=POLICY)

    assert status == VersionStatus.FAILED.value
    assert db_session.get(FileVersion, version_id).error_code == REASON_SOURCE_CHANGED


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

