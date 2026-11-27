"""TXT/Markdown extraction is strict, bounded, and independent of PDF parsing."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import Relationship, SourceChunk, VersionStatus
from services.parsing.chunking import CHUNK_SIZE_CHARS, chunk_document
from services.parsing.handler import handle_extract_file
from services.parsing.text import (
    REASON_TEXT_BINARY,
    REASON_TEXT_EMPTY,
    REASON_TEXT_ENCODING,
    REASON_TEXT_TOO_LARGE,
    TEXT_MAX_BYTES,
    TextParsingPolicy,
    verify_native_source,
)
from services.parsing.pdf import (
    REASON_SOURCE_CHANGED,
    REASON_UNSUPPORTED_FORMAT,
    SourceChanged,
    UnsupportedDocument,
    extract_document,
)

POLICY = TextParsingPolicy(enabled=True)


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _reason(path: Path) -> str:
    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(path, text_policy=POLICY)
    return excinfo.value.reason_code


def test_txt_accepts_strict_utf8_and_normalizes_lf_and_crlf(tmp_path):
    path = _write(tmp_path / "notes.txt", "第一行\r\nsecond line\n".encode("utf-8"))

    document = extract_document(path, text_policy=POLICY)

    assert document.source_kind == "text"
    assert document.page_count == 1
    assert document.pages[0].page_number is None
    assert document.pages[0].text == "第一行\nsecond line\n"


def test_utf8_bom_is_accepted_and_removed(tmp_path):
    path = _write(
        tmp_path / "bom.txt",
        b"\xef\xbb\xbfhello from a BOM file",
    )

    document = extract_document(path, text_policy=POLICY)

    assert document.pages[0].text == "hello from a BOM file"


def test_markdown_is_plain_text_and_html_is_not_rendered(tmp_path):
    path = _write(
        tmp_path / "notes.md",
        b"# Heading\n<script src='https://example.invalid/x.js'></script>\n",
    )

    document = extract_document(path, text_policy=POLICY)

    assert document.source_kind == "markdown"
    assert "<script" in document.pages[0].text
    assert "https://example.invalid" in document.pages[0].text


def test_native_chunking_preserves_hyphen_line_breaks_and_indentation(tmp_path):
    path = _write(
        tmp_path / "code.md",
        b"feature-\nready\n    indented code\n",
    )

    chunks = chunk_document(extract_document(path, text_policy=POLICY))

    assert chunks[0].text == "feature-\nready\n    indented code\n"


@pytest.mark.parametrize("prefix", ["", "Opening line\n"], ids=["leading", "interior"])
def test_native_chunking_skips_blank_slices_without_trimming_passages(tmp_path, prefix):
    closing = "    indented code\n"
    text = prefix + "\n" * (2 * CHUNK_SIZE_CHARS) + closing
    path = _write(tmp_path / "notes.md", text.encode("utf-8"))

    chunks = chunk_document(extract_document(path, text_policy=POLICY))

    assert chunks
    assert all(chunk.text.strip() for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert chunks[-1].text.endswith(closing)
    if prefix:
        assert chunks[0].text.startswith(prefix + "\n")


def test_pdf_signature_wins_over_an_enabled_text_suffix(tmp_path):
    source = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / "normal.pdf"
    disguised_pdf = tmp_path / "renamed.txt"
    shutil.copyfile(source, disguised_pdf)

    document = extract_document(disguised_pdf, text_policy=POLICY)

    assert document.source_kind == "pdf"
    assert document.page_count == 3


def test_empty_text_has_an_explicit_reason(tmp_path):
    path = _write(tmp_path / "empty.txt", b" \r\n\t\n")

    assert _reason(path) == REASON_TEXT_EMPTY


def test_invalid_utf8_has_an_explicit_reason(tmp_path):
    path = _write(tmp_path / "binary-encoding.txt", b"valid prefix \xff")

    assert _reason(path) == REASON_TEXT_ENCODING


def test_native_source_replaced_during_final_recheck_is_not_accepted(tmp_path, monkeypatch):
    original = b"old passage"
    path = _write(tmp_path / "notes.txt", original)
    replacement = _write(tmp_path / "replacement.txt", b"new passage")
    real_stat = Path.stat
    replaced = False

    def stat_after_replacement(candidate, **kwargs):
        nonlocal replaced
        if candidate == path and not replaced:
            # The verifier has read the old bytes by the time it checks the path.
            replacement.replace(path)
            replaced = True
        return real_stat(candidate, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_after_replacement)
    with pytest.raises(SourceChanged) as excinfo:
        verify_native_source(
            path, content_sha256=hashlib.sha256(original).hexdigest(), byte_size=len(original)
        )

    assert replaced
    assert excinfo.value.reason_code == REASON_SOURCE_CHANGED


def test_nul_and_control_bytes_are_treated_as_binary(tmp_path):
    path = _write(tmp_path / "binary.txt", b"hello\x00world")

    assert _reason(path) == REASON_TEXT_BINARY


def test_text_size_limit_is_two_mib(tmp_path):
    path = _write(tmp_path / "large.txt", b"a" * (TEXT_MAX_BYTES + 1))

    assert _reason(path) == REASON_TEXT_TOO_LARGE


def test_a_configured_limit_cannot_raise_the_hard_two_mib_cap(tmp_path):
    configured = TextParsingPolicy(enabled=True, max_bytes=TEXT_MAX_BYTES * 10)
    path = _write(tmp_path / "large.txt", b"a" * (TEXT_MAX_BYTES + 1))

    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(path, text_policy=configured)

    assert excinfo.value.reason_code == REASON_TEXT_TOO_LARGE


def test_text_is_disabled_by_default_and_preserves_pdf_style_unsupported(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TEXT_PARSING_ENABLED", raising=False)
    monkeypatch.delenv("PARSING_TEXT_ENABLED", raising=False)
    path = _write(tmp_path / "notes.txt", b"plain text")

    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(path)

    assert excinfo.value.reason_code == REASON_UNSUPPORTED_FORMAT


def test_environment_enables_text_extraction(tmp_path, monkeypatch):
    path = _write(tmp_path / "notes.txt", b"enabled by A config")
    monkeypatch.setenv("TEXT_PARSING_ENABLED", "true")

    document = extract_document(path)

    assert document.pages[0].text == "enabled by A config"


def test_text_handler_stores_null_pages_without_relation_candidates(
    db_session: Session, make_file_version, tmp_path
):
    path = _write(tmp_path / "notes.txt", b"plain notes for search")
    version_id = make_file_version(source_path=path)

    status = handle_extract_file(
        db_session,
        version_id,
        path,
        text_policy=POLICY,
    )

    assert status == VersionStatus.BASIC_READY.value
    chunks = (
        db_session.execute(
            select(SourceChunk).where(SourceChunk.version_id == version_id)
        )
        .scalars()
        .all()
    )
    assert chunks
    assert all(chunk.page_number is None for chunk in chunks)
    assert (
        db_session.execute(
            select(Relationship).where(Relationship.source_version_id == version_id)
        )
        .scalars()
        .all()
        == []
    )


def test_an_invalid_text_file_does_not_block_the_next_valid_file(
    db_session: Session, make_file_version, tmp_path
):
    bad = _write(tmp_path / "bad.txt", b"\xff")
    good = _write(tmp_path / "good.txt", b"a valid text document")
    bad_version = make_file_version(source_path=bad)
    good_version = make_file_version(source_path=good)

    assert handle_extract_file(db_session, bad_version, bad, text_policy=POLICY) == (
        VersionStatus.UNSUPPORTED.value
    )
    assert handle_extract_file(db_session, good_version, good, text_policy=POLICY) == (
        VersionStatus.BASIC_READY.value
    )

