"""Store the chunks of one file version.

Two rules shape this module:

1. **Replace, do not append.** A file version is identified by its content
   hash, so the same version always produces the same chunks. Re-processing
   must land on the same rows rather than adding a second copy. That also
   means a parser upgrade can safely re-run: the version's chunk set is
   replaced with the new one.

2. **Delete and insert are one transaction.** Replacing means removing the old
   rows first. If the insert then fails, the delete must roll back too,
   otherwise a failed re-parse would leave the version with no chunks at all -
   worse than not running it.

The caller owns the session; this module owns the transaction for its own
operation and leaves the session usable either way.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.orm import Session

from services.common.models import SourceChunk
from services.parsing.chunking import Chunk


class InvalidChunkSet(ValueError):
    """The chunk set is malformed and was not written."""


def _validate_ordinals(chunks: Sequence[Chunk]) -> None:
    """Reject a malformed chunk set before touching the database.

    Only the shape of the set is checked here. Anything the database enforces
    (non-empty text, a known version) is left to the database so that a real
    failure exercises the rollback path rather than being caught early.
    """
    ordinals = [chunk.ordinal for chunk in chunks]
    if any(ordinal < 1 for ordinal in ordinals):
        raise InvalidChunkSet("chunk ordinals must start at 1")
    if len(set(ordinals)) != len(ordinals):
        raise InvalidChunkSet("chunk ordinals must be unique within a version")


def persist_chunks(db: Session, version_id: str, chunks: Sequence[Chunk]) -> int:
    """Replace the stored chunks of ``version_id`` with ``chunks``.

    Returns the number of chunks written. The whole replace is one
    transaction: on any failure the previous chunks are left untouched and the
    exception is re-raised for the caller to record against the job.
    """
    _validate_ordinals(chunks)

    try:
        db.execute(delete(SourceChunk).where(SourceChunk.version_id == version_id))
        for chunk in chunks:
            db.add(
                SourceChunk(
                    version_id=version_id,
                    ordinal=chunk.ordinal,
                    page_number=chunk.page_number,
                    text=chunk.text,
                )
            )
        db.commit()
    except Exception:
        # Undo the delete along with the partial insert.
        db.rollback()
        raise

    return len(chunks)
