"""Tests for writing chunks against a file version.

These cover the three cases the schedule asks for: a normal write, a repeated
write of the same version, and a write that fails part way through.
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
    VersionStatus,
)
from services.parsing.chunking import Chunk
from services.parsing.persist import InvalidChunkSet, persist_chunks


def _make_version(db: Session, sha256: str = "a" * 64) -> str:
    """Create the root -> file -> version chain a chunk row has to hang off."""
    # Root paths are unique per mount, so key them off the content hash to keep
    # this helper reusable for more than one version in a single test.
    key = sha256[:8]
    root = AuthorizedRoot(
        mount_id=f"collection-{key}",
        relative_path=f"reports-{key}",
        status=RootStatus.ACTIVE.value,
    )
    db.add(root)
    db.flush()

    file_record = FileRecord(
        root_id=root.id,
        relative_path=f"reports-{key}/invoice.pdf",
        name="invoice.pdf",
        presence_status=FilePresence.PRESENT.value,
    )
    db.add(file_record)
    db.flush()

    version = FileVersion(
        file_id=file_record.id,
        content_sha256=sha256,
        byte_size=1234,
        status=VersionStatus.DISCOVERED.value,
    )
    db.add(version)
    db.commit()
    return version.id


def _stored(db: Session, version_id: str) -> list[SourceChunk]:
    statement = (
        select(SourceChunk)
        .where(SourceChunk.version_id == version_id)
        .order_by(SourceChunk.ordinal)
    )
    return list(db.execute(statement).scalars().all())


SAMPLE = [
    Chunk(ordinal=1, page_number=1, text="first chunk of page one"),
    Chunk(ordinal=2, page_number=1, text="second chunk of page one"),
    Chunk(ordinal=3, page_number=2, text="first chunk of page two"),
]


def test_persist_chunks_writes_ordinals_pages_and_text(db_session: Session):
    version_id = _make_version(db_session)

    written = persist_chunks(db_session, version_id, SAMPLE)

    assert written == 3
    rows = _stored(db_session, version_id)
    assert [row.ordinal for row in rows] == [1, 2, 3]
    assert [row.page_number for row in rows] == [1, 1, 2]
    assert rows[2].text == "first chunk of page two"
    assert all(row.id for row in rows)


def test_persisting_the_same_version_twice_does_not_duplicate(db_session: Session):
    version_id = _make_version(db_session)

    persist_chunks(db_session, version_id, SAMPLE)
    persist_chunks(db_session, version_id, SAMPLE)

    rows = _stored(db_session, version_id)
    assert len(rows) == 3, "re-processing a version must replace, not append"
    assert [row.ordinal for row in rows] == [1, 2, 3]


def test_reprocessing_replaces_the_previous_chunk_set(db_session: Session):
    version_id = _make_version(db_session)
    persist_chunks(db_session, version_id, SAMPLE)

    # A parser revision produces a different chunk set for the same version.
    revised = [
        Chunk(ordinal=1, page_number=1, text="revised chunk one"),
        Chunk(ordinal=2, page_number=2, text="revised chunk two"),
    ]
    persist_chunks(db_session, version_id, revised)

    rows = _stored(db_session, version_id)
    assert [row.text for row in rows] == ["revised chunk one", "revised chunk two"]


def test_failed_write_rolls_back_and_keeps_the_previous_chunks(db_session: Session):
    version_id = _make_version(db_session)
    persist_chunks(db_session, version_id, SAMPLE)

    # Second chunk has no text, which the database rejects on insert. This is a
    # real database failure, not a pre-check, so it exercises the rollback.
    broken = [
        Chunk(ordinal=1, page_number=1, text="replacement one"),
        Chunk(ordinal=2, page_number=1, text=None),  # type: ignore[arg-type]
    ]

    with pytest.raises(Exception):
        persist_chunks(db_session, version_id, broken)

    rows = _stored(db_session, version_id)
    assert len(rows) == 3, "a failed replace must not delete the existing chunks"
    assert [row.text for row in rows] == [chunk.text for chunk in SAMPLE]


def test_session_is_still_usable_after_a_failed_write(db_session: Session):
    version_id = _make_version(db_session)
    persist_chunks(db_session, version_id, SAMPLE)

    with pytest.raises(Exception):
        persist_chunks(
            db_session,
            version_id,
            [Chunk(ordinal=1, page_number=1, text=None)],  # type: ignore[arg-type]
        )

    # The rollback must leave the session usable, not poisoned.
    persist_chunks(db_session, version_id, SAMPLE)
    assert len(_stored(db_session, version_id)) == 3


def test_duplicate_ordinals_are_rejected_before_writing(db_session: Session):
    version_id = _make_version(db_session)

    with pytest.raises(InvalidChunkSet):
        persist_chunks(
            db_session,
            version_id,
            [
                Chunk(ordinal=1, page_number=1, text="one"),
                Chunk(ordinal=1, page_number=2, text="also one"),
            ],
        )

    assert _stored(db_session, version_id) == []


def test_chunks_of_different_versions_are_independent(db_session: Session):
    first = _make_version(db_session, sha256="a" * 64)
    second = _make_version(db_session, sha256="b" * 64)

    persist_chunks(db_session, first, SAMPLE)
    persist_chunks(
        db_session, second, [Chunk(ordinal=1, page_number=1, text="other document")]
    )

    assert len(_stored(db_session, first)) == 3
    assert len(_stored(db_session, second)) == 1
