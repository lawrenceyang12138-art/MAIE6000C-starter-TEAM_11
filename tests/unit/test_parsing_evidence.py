"""Tests for reading a stored passage back as current evidence.

The interesting cases are the refusals: a passage that used to be valid must
stop being served the moment its version is superseded, its file disappears, or
its folder authorisation is revoked.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import pytest

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    RootStatus,
    SourceChunk,
)
from services.parsing.chunking import Chunk
from services.parsing.evidence import (
    REASON_CHUNK_NOT_FOUND,
    REASON_FILE_MISSING,
    REASON_NO_CURRENT_VERSION,
    REASON_ROOT_REVOKED,
    REASON_VERSION_SUPERSEDED,
    SourceUnavailable,
    read_evidence,
)
from services.parsing.persist import persist_chunks


def _ready_chunks(
    db: Session, make_file_version, sha256: str, chunks: list[Chunk]
) -> list[str]:
    """Create a version that is the file's current version, with chunks stored."""
    version_id = make_file_version(sha256=sha256)
    version = db.get(FileVersion, version_id)
    file_record = db.get(FileRecord, version.file_id)
    file_record.current_version_id = version_id
    db.commit()

    persist_chunks(db, version_id, chunks)
    rows = db.execute(
        select(SourceChunk)
        .where(SourceChunk.version_id == version_id)
        .order_by(SourceChunk.ordinal)
    ).scalars().all()
    return [row.id for row in rows]


SIMPLE = [
    Chunk(ordinal=1, page_number=1, text="the first passage"),
    Chunk(ordinal=2, page_number=2, text="the second passage"),
]


def test_reading_a_current_passage_returns_it_with_its_citation(
    db_session: Session, make_file_version
):
    chunk_ids = _ready_chunks(db_session, make_file_version, "a" * 64, SIMPLE)

    evidence = read_evidence(db_session, chunk_ids[1])

    assert evidence.text == "the second passage"
    assert evidence.page_number == 2
    assert evidence.ordinal == 2
    assert evidence.content_sha256 == "a" * 64
    assert evidence.relative_path.endswith("invoice.pdf")


def test_unknown_chunk_is_refused(db_session: Session):
    with pytest.raises(SourceUnavailable) as excinfo:
        read_evidence(db_session, "00000000-0000-0000-0000-000000000000")

    assert excinfo.value.reason_code == REASON_CHUNK_NOT_FOUND


def test_a_superseded_version_stops_being_served(
    db_session: Session, make_file_version
):
    old_chunk_ids = _ready_chunks(db_session, make_file_version, "a" * 64, SIMPLE)

    # The file now points at newer content.
    old_version = db_session.get(FileVersion, _version_of(db_session, old_chunk_ids[0]))
    file_record = db_session.get(FileRecord, old_version.file_id)
    file_record.current_version_id = "11111111-1111-1111-1111-111111111111"
    db_session.commit()

    with pytest.raises(SourceUnavailable) as excinfo:
        read_evidence(db_session, old_chunk_ids[0])

    assert excinfo.value.reason_code == REASON_VERSION_SUPERSEDED


def test_a_file_with_no_current_version_is_treated_as_stale(
    db_session: Session, make_file_version
):
    """Nothing has marked a version current yet, which is not the same as
    "the file has newer content" - the fix for each is different."""
    version_id = make_file_version(sha256="a" * 64)
    # Deliberately do not set current_version_id.
    persist_chunks(db_session, version_id, SIMPLE)
    chunk_id = _first_chunk(db_session, version_id)

    with pytest.raises(SourceUnavailable) as excinfo:
        read_evidence(db_session, chunk_id)

    assert excinfo.value.reason_code == REASON_NO_CURRENT_VERSION
    assert "newer content" not in excinfo.value.message


def test_the_two_staleness_reasons_are_distinguishable(
    db_session: Session, make_file_version
):
    """One says "you are behind", the other says "nobody set a current version"."""
    stale_ids = _ready_chunks(db_session, make_file_version, "a" * 64, SIMPLE)
    version = db_session.get(FileVersion, _version_of(db_session, stale_ids[0]))
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.current_version_id = "11111111-1111-1111-1111-111111111111"
    db_session.commit()

    with pytest.raises(SourceUnavailable) as superseded:
        read_evidence(db_session, stale_ids[0])

    file_record.current_version_id = None
    db_session.commit()

    with pytest.raises(SourceUnavailable) as unset:
        read_evidence(db_session, stale_ids[0])

    assert superseded.value.reason_code == REASON_VERSION_SUPERSEDED
    assert unset.value.reason_code == REASON_NO_CURRENT_VERSION
    assert superseded.value.message != unset.value.message


def test_a_missing_file_stops_being_served(db_session: Session, make_file_version):
    chunk_ids = _ready_chunks(db_session, make_file_version, "a" * 64, SIMPLE)

    version = db_session.get(FileVersion, _version_of(db_session, chunk_ids[0]))
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.presence_status = FilePresence.MISSING.value
    db_session.commit()

    with pytest.raises(SourceUnavailable) as excinfo:
        read_evidence(db_session, chunk_ids[0])

    assert excinfo.value.reason_code == REASON_FILE_MISSING


def test_a_revoked_folder_stops_being_served(db_session: Session, make_file_version):
    chunk_ids = _ready_chunks(db_session, make_file_version, "a" * 64, SIMPLE)

    version = db_session.get(FileVersion, _version_of(db_session, chunk_ids[0]))
    file_record = db_session.get(FileRecord, version.file_id)
    root = db_session.get(AuthorizedRoot, file_record.root_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    with pytest.raises(SourceUnavailable) as excinfo:
        read_evidence(db_session, chunk_ids[0])

    assert excinfo.value.reason_code == REASON_ROOT_REVOKED


def test_ten_passages_resolve_to_the_page_they_were_stored_on(
    db_session: Session, make_file_version
):
    """The page-location sample set the schedule asks for."""
    chunks = [
        Chunk(ordinal=index, page_number=(index + 1) // 2, text=f"passage number {index}")
        for index in range(1, 11)
    ]
    chunk_ids = _ready_chunks(db_session, make_file_version, "b" * 64, chunks)

    assert len(chunk_ids) == 10

    for index, chunk_id in enumerate(chunk_ids, start=1):
        evidence = read_evidence(db_session, chunk_id)
        assert evidence.text == f"passage number {index}"
        assert evidence.page_number == (index + 1) // 2
        assert evidence.ordinal == index


def _version_of(db: Session, chunk_id: str) -> str:
    return db.get(SourceChunk, chunk_id).version_id


def _first_chunk(db: Session, version_id: str) -> str:
    return db.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().first().id
