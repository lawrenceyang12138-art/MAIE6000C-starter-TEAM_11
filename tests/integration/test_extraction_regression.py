"""The 12 normal / 3 abnormal / 1 unsupported regression the schedule asks for.

This is a rehearsal corpus: `tests/fixtures/regression/` holds twelve generated
PDFs across two subdirectories, each page carrying a marker word naming its
document and page number. When the official fixture corpus lands, only the file
list changes - the assertions stay the same.

Each normal page carries a marker like ``Marker03P2``. Checking that marker on
the chunk's claimed page is a direct test of page mapping across twelve
documents rather than one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import FileVersion, SourceChunk, VersionStatus
from services.parsing.handler import handle_extract_file
from services.parsing.pdf import (
    REASON_CORRUPT,
    REASON_ENCRYPTED,
    REASON_NO_TEXT_LAYER,
    REASON_UNSUPPORTED_FORMAT,
    file_identity,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NORMAL = sorted((FIXTURES / "regression").glob("group-*/*.pdf"))
UNSUPPORTED = FIXTURES / "regression" / "unsupported.txt"
ABNORMAL = [
    (FIXTURES / "parsing" / "encrypted.pdf", REASON_ENCRYPTED),
    (FIXTURES / "parsing" / "corrupt.pdf", REASON_CORRUPT),
    (FIXTURES / "parsing" / "no_text_layer.pdf", REASON_NO_TEXT_LAYER),
]


def _chunks(db: Session, version_id: str) -> list[SourceChunk]:
    return list(
        db.execute(
            select(SourceChunk)
            .where(SourceChunk.version_id == version_id)
            .order_by(SourceChunk.ordinal)
        )
        .scalars()
        .all()
    )


def test_the_rehearsal_corpus_matches_the_planned_shape():
    assert len(NORMAL) == 12
    assert len(ABNORMAL) == 3
    assert UNSUPPORTED.exists()
    # The fixtures must span at least two subdirectories.
    assert len({path.parent.name for path in NORMAL}) >= 2


def test_twelve_normal_documents_extract_with_correct_pages(
    db_session: Session, make_file_version
):
    for path in NORMAL:
        sha256, _ = file_identity(path)
        version_id = make_file_version(sha256=sha256)

        status = handle_extract_file(db_session, version_id, path)
        assert status == VersionStatus.BASIC_READY.value, f"{path.name} did not extract"

        chunks = _chunks(db_session, version_id)
        assert chunks, f"{path.name} produced no chunks"

        # Every chunk must carry the marker of the page it claims, and the set
        # of pages found must match the pages the document actually has.
        markers_on_page: dict[int, set[str]] = {}
        for chunk in chunks:
            found = set(re.findall(r"Marker\d{2}P\d+", chunk.text))
            assert found, f"{path.name} chunk {chunk.ordinal} lost its marker"
            markers_on_page.setdefault(chunk.page_number, set()).update(found)

        for page_number, markers in markers_on_page.items():
            for marker in markers:
                suffix = int(marker.rsplit("P", 1)[1])
                assert suffix == page_number, (
                    f"{path.name}: {marker} stored on page {page_number}"
                )


@pytest.mark.parametrize(("path", "expected_reason"), ABNORMAL)
def test_three_abnormal_documents_report_distinct_reasons(
    db_session: Session, make_file_version, path: Path, expected_reason: str
):
    version_id = make_file_version(sha256="f" * 64)

    status = handle_extract_file(db_session, version_id, path)

    assert status == VersionStatus.UNSUPPORTED.value
    assert db_session.get(FileVersion, version_id).error_code == expected_reason
    assert _chunks(db_session, version_id) == []


def test_a_non_pdf_is_reported_as_unsupported_rather_than_corrupt(
    db_session: Session, make_file_version
):
    version_id = make_file_version(sha256="e" * 64)

    status = handle_extract_file(db_session, version_id, UNSUPPORTED)

    assert status == VersionStatus.UNSUPPORTED.value
    # "We do not handle this file type" is a different message from "your PDF
    # is broken", and the user needs the right one.
    assert db_session.get(FileVersion, version_id).error_code == REASON_UNSUPPORTED_FORMAT


def test_a_mix_of_files_is_processed_without_stopping(
    db_session: Session, make_file_version
):
    """The whole corpus in one pass, as a scan would present it."""
    outcomes: dict[str, str] = {}

    for path in NORMAL:
        sha256, _ = file_identity(path)
        version_id = make_file_version(sha256=sha256)
        outcomes[path.name] = handle_extract_file(db_session, version_id, path)

    for path, _ in ABNORMAL:
        # A distinct but arbitrary hash: these versions are only used to hold
        # the outcome, not to match the file on disk.
        version_id = make_file_version(sha256=(path.stem * 64)[:64])
        outcomes[path.name] = handle_extract_file(db_session, version_id, path)

    assert sum(1 for status in outcomes.values() if status == "basic_ready") == 12
    assert sum(1 for status in outcomes.values() if status == "unsupported") == 3
