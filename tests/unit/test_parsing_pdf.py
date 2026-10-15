"""Tests for per-page PDF text extraction.

Fixtures in tests/fixtures/parsing/ are synthetic and regenerable; see the
README in that directory. They are deliberately tiny so they can live in git.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.parsing.pdf import (
    REASON_CORRUPT,
    REASON_ENCRYPTED,
    REASON_FILE_MISSING,
    REASON_NO_TEXT_LAYER,
    SourceMissing,
    UnsupportedDocument,
    extract_document,
    file_identity,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def test_extract_document_keeps_page_numbers():
    doc = extract_document(FIXTURES / "normal.pdf")

    assert doc.page_count == 3
    assert [page.page_number for page in doc.pages] == [1, 2, 3]

    # Each page keeps its own text, in document order. If page numbering drifted
    # this would silently attach text to the wrong page.
    assert "ALPHA" in doc.pages[0].text
    assert "BRAVO" in doc.pages[1].text
    assert "CHARLIE" in doc.pages[2].text


def test_extract_document_reports_file_identity():
    path = FIXTURES / "normal.pdf"

    doc = extract_document(path)
    expected_hash, expected_size = file_identity(path)

    assert doc.content_sha256 == expected_hash
    assert len(doc.content_sha256) == 64
    assert doc.byte_size == expected_size == path.stat().st_size


def test_extract_document_does_not_modify_the_source_file():
    path = FIXTURES / "normal.pdf"

    before = file_identity(path)
    extract_document(path)
    after = file_identity(path)

    assert before == after, "parsing must never change the original file"


@pytest.mark.parametrize(
    ("filename", "expected_reason"),
    [
        ("encrypted.pdf", REASON_ENCRYPTED),
        ("corrupt.pdf", REASON_CORRUPT),
        ("no_text_layer.pdf", REASON_NO_TEXT_LAYER),
    ],
)
def test_abnormal_documents_are_rejected_with_a_specific_reason(
    filename: str, expected_reason: str
):
    with pytest.raises(UnsupportedDocument) as excinfo:
        extract_document(FIXTURES / filename)

    assert excinfo.value.reason_code == expected_reason
    assert excinfo.value.message


def test_a_missing_file_is_not_reported_as_a_bad_document():
    """Not the same failure, and not the same fix either.

    "We cannot handle this kind of document" and "the file is not there" lead
    the reader in different directions, so a missing file gets its own
    exception rather than another unsupported-document reason.
    """
    missing = FIXTURES / "definitely-not-here.pdf"

    with pytest.raises(SourceMissing) as excinfo:
        extract_document(missing)

    assert excinfo.value.reason_code == REASON_FILE_MISSING
    assert "No such file" in excinfo.value.message


def test_identifying_a_missing_file_says_so():
    with pytest.raises(SourceMissing) as excinfo:
        file_identity(FIXTURES / "definitely-not-here.pdf")

    assert excinfo.value.reason_code == REASON_FILE_MISSING
