"""Tests for the extraction handler the worker calls.

These cover the outcome the handler must record for each kind of input, and the
requirement that one bad document does not stop the file after it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import FileVersion, SourceChunk, VersionStatus
from services.parsing.handler import (
    PARSER_REVISION,
    REASON_PROCESSING_FAILED,
    REASON_SOURCE_CHANGED,
    handle_extract_file,
)
from services.parsing.pdf import (
    REASON_CORRUPT,
    REASON_ENCRYPTED,
    REASON_FILE_MISSING,
    REASON_NO_TEXT_LAYER,
    file_identity,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"


def _chunks(db: Session, version_id: str) -> list[SourceChunk]:
    return list(
        db.execute(
            select(SourceChunk).where(SourceChunk.version_id == version_id)
        )
        .scalars()
        .all()
    )


def test_successful_extraction_marks_the_version_and_stores_chunks(
    db_session: Session, make_file_version
):
    real_hash, _ = file_identity(FIXTURES / "normal.pdf")
    version_id = make_file_version(sha256=real_hash)

    status = handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")

    assert status == VersionStatus.BASIC_READY.value

    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.BASIC_READY.value
    assert version.error_code is None
    assert version.parser_revision == PARSER_REVISION

    chunks = _chunks(db_session, version_id)
    assert len(chunks) == 3
    assert sorted(chunk.page_number for chunk in chunks) == [1, 2, 3]


@pytest.mark.parametrize(
    ("filename", "expected_reason"),
    [
        ("encrypted.pdf", REASON_ENCRYPTED),
        ("corrupt.pdf", REASON_CORRUPT),
        ("no_text_layer.pdf", REASON_NO_TEXT_LAYER),
    ],
)
def test_a_bad_document_is_recorded_rather_than_raised(
    db_session: Session, make_file_version, filename: str, expected_reason: str
):
    version_id = make_file_version(sha256="c" * 64)

    # The whole point: this must return, not raise, so the worker loop survives.
    status = handle_extract_file(db_session, version_id, FIXTURES / filename)

    assert status == VersionStatus.UNSUPPORTED.value

    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.UNSUPPORTED.value
    assert version.error_code == expected_reason
    assert version.parser_revision == PARSER_REVISION
    assert _chunks(db_session, version_id) == []


def test_a_version_whose_file_changed_is_not_published(
    db_session: Session, make_file_version
):
    # The version claims a different hash than the file on disk actually has,
    # which is what happens when the file is edited while we are reading it.
    version_id = make_file_version(sha256="d" * 64)

    status = handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")

    assert status == VersionStatus.FAILED.value

    version = db_session.get(FileVersion, version_id)
    assert version.error_code == REASON_SOURCE_CHANGED
    assert _chunks(db_session, version_id) == [], (
        "text from different bytes must never be stored against this version"
    )


def test_unknown_version_is_a_programming_error(db_session: Session):
    with pytest.raises(LookupError):
        handle_extract_file(db_session, "00000000-0000-0000-0000-000000000000", FIXTURES)


def test_a_file_deleted_between_scan_and_parse_is_recorded_not_raised(
    db_session: Session, make_file_version
):
    """A file can vanish between being scanned and being read.

    That used to raise out of the handler, leaving the version stuck in
    "extracting" with the worker's failed job as the only trace of why.
    """
    version_id = make_file_version(sha256="e" * 64)

    status = handle_extract_file(
        db_session, version_id, FIXTURES / "not-there.pdf"
    )

    assert status == VersionStatus.FAILED.value

    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_FILE_MISSING
    assert _chunks(db_session, version_id) == []


def test_a_file_written_during_the_read_is_recorded_not_published(
    db_session: Session, make_file_version, tmp_path, monkeypatch
):
    """The version's hash and the text must come from the same bytes.

    The check below the extraction only compares the version row with the file
    before the read; this covers a write that lands during the read itself.
    """
    import shutil

    from services.parsing import pdf as pdf_module

    target = tmp_path / "doc.pdf"
    shutil.copy(FIXTURES / "normal.pdf", target)
    real_hash, _ = file_identity(target)
    version_id = make_file_version(sha256=real_hash)

    real_read_pages = pdf_module._read_pages

    def read_then_write(path):
        pages = real_read_pages(path)
        with target.open("ab") as handle:
            handle.write(b"\n% a late edit\n")
        return pages

    monkeypatch.setattr(pdf_module, "_read_pages", read_then_write)

    status = handle_extract_file(db_session, version_id, target)

    assert status == VersionStatus.FAILED.value
    version = db_session.get(FileVersion, version_id)
    assert version.error_code == REASON_SOURCE_CHANGED
    assert _chunks(db_session, version_id) == []


def test_a_failure_while_storing_does_not_leave_the_version_extracting(
    db_session: Session, make_file_version, monkeypatch
):
    """A row stuck in "extracting" is indistinguishable from one still running."""
    import services.parsing.handler as handler_module

    real_hash, _ = file_identity(FIXTURES / "normal.pdf")
    version_id = make_file_version(sha256=real_hash)

    def explode(*args, **kwargs):
        raise RuntimeError("the database said no")

    monkeypatch.setattr(handler_module, "persist_chunks", explode)

    with pytest.raises(RuntimeError):
        handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")

    db_session.rollback()
    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_PROCESSING_FAILED


def test_a_crash_inside_the_reader_does_not_leave_the_version_extracting(
    db_session: Session, make_file_version, monkeypatch
):
    """The same guarantee as the test above, for the extraction step.

    `extract_document` is written to raise only the three document exceptions,
    but a library bug or an I/O error is not bound by that promise. Before this
    test, such a crash left the row saying "extracting" forever - the exact
    failure the storing test was written for, one step earlier.
    """
    import services.parsing.handler as handler_module

    real_hash, _ = file_identity(FIXTURES / "normal.pdf")
    version_id = make_file_version(sha256=real_hash)

    def explode(*args, **kwargs):
        raise RuntimeError("the reader crashed")

    monkeypatch.setattr(handler_module, "extract_document", explode)

    with pytest.raises(RuntimeError):
        handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")

    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_PROCESSING_FAILED
    assert _chunks(db_session, version_id) == []


def test_a_failure_on_the_final_status_commit_does_not_leave_extracting(
    db_session: Session, make_file_version, monkeypatch
):
    """The last commit can fail just like the earlier ones.

    Chunks are committed before the version is marked ready. If that final
    commit fails, the row must still receive a failed outcome rather than
    staying indistinguishable from work that is still running.
    """
    real_hash, _ = file_identity(FIXTURES / "normal.pdf")
    version_id = make_file_version(sha256=real_hash)
    real_commit = db_session.commit
    calls = {"count": 0}

    def commit_with_one_failure():
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("the final status commit failed")
        real_commit()

    monkeypatch.setattr(db_session, "commit", commit_with_one_failure)

    with pytest.raises(RuntimeError):
        handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")

    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_PROCESSING_FAILED
    assert version.parser_revision == PARSER_REVISION


def test_one_bad_file_does_not_stop_the_next_one(
    db_session: Session, make_file_version
):
    """The behaviour the schedule requires: a failure is isolated to its file."""
    real_hash, _ = file_identity(FIXTURES / "normal.pdf")

    bad_version = make_file_version(sha256="e" * 64)
    good_version = make_file_version(sha256=real_hash)

    # A broken document first, then a good one, as a worker loop would see them.
    assert (
        handle_extract_file(db_session, bad_version, FIXTURES / "corrupt.pdf")
        == VersionStatus.UNSUPPORTED.value
    )
    assert (
        handle_extract_file(db_session, good_version, FIXTURES / "normal.pdf")
        == VersionStatus.BASIC_READY.value
    )

    assert len(_chunks(db_session, good_version)) == 3


def test_reprocessing_the_same_version_replaces_the_chunks(
    db_session: Session, make_file_version
):
    real_hash, _ = file_identity(FIXTURES / "normal.pdf")
    version_id = make_file_version(sha256=real_hash)

    handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")
    first = {(chunk.ordinal, chunk.text) for chunk in _chunks(db_session, version_id)}

    handle_extract_file(db_session, version_id, FIXTURES / "normal.pdf")
    second = {(chunk.ordinal, chunk.text) for chunk in _chunks(db_session, version_id)}

    assert first == second
    assert len(second) == 3, "re-processing must not duplicate chunks"
