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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.common.models import (
    Entity,
    RelationKind,
    RelationOrigin,
    RelationType,
    Relationship,
    RelationshipEvidence,
    SourceChunk,
)
from services.parsing.chunking import Chunk
from services.parsing.relations import CandidateRelation


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

    A chunk whose ordinal, page and text are unchanged **keeps its row**, and
    therefore its id. That is not an optimisation: relationship evidence points
    at chunk ids with a cascading foreign key, so deleting and recreating
    identical rows would silently strip the evidence from every relation that
    cites them. Re-processing a version with the same parser used to do exactly
    that, leaving relations whose quotes had gone missing.

    A chunk whose text or page did change is replaced, and the evidence that
    pointed at it is dropped by the database rather than left claiming a quote
    that the chunk no longer contains.
    """
    _validate_ordinals(chunks)

    try:
        existing = {
            row.ordinal: row
            for row in db.execute(
                select(SourceChunk).where(SourceChunk.version_id == version_id)
            )
            .scalars()
            .all()
        }
        incoming = {chunk.ordinal for chunk in chunks}

        to_delete: list[SourceChunk] = []
        to_insert: list[Chunk] = []
        for chunk in chunks:
            row = existing.get(chunk.ordinal)
            if (
                row is not None
                and row.text == chunk.text
                and row.page_number == chunk.page_number
            ):
                continue
            if row is not None:
                to_delete.append(row)
            to_insert.append(chunk)

        for ordinal, row in existing.items():
            if ordinal not in incoming:
                to_delete.append(row)

        for row in to_delete:
            db.delete(row)

        # The delete has to reach the database before a replacement is
        # inserted for the same ordinal: the table is unique on
        # (version_id, ordinal), and the unit of work does not promise an order.
        db.flush()

        for chunk in to_insert:
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


def persist_relations(
    db: Session, version_id: str, candidates: Sequence[CandidateRelation]
) -> int:
    """Store entity candidates and the evidence that supports each one.

    Entities and relationships are found-or-created rather than replaced, so a
    relationship keeps its row id across re-runs. That matters later: a human
    review points at a relationship, and replacing the row would silently throw
    the review away.

    Evidence rows are refreshed for each relationship, because they carry
    offsets into chunk text and a parser change moves them.

    The chunks must already be stored: evidence is attached to a stored chunk,
    and the chunk is resolved by its ordinal within this version.
    """
    written = 0
    for candidate in candidates:
        entity = (
            db.execute(
                select(Entity).where(
                    Entity.entity_type == candidate.entity_type,
                    Entity.normalized_label == candidate.normalized_label,
                )
            )
            .scalars()
            .first()
        )
        if entity is None:
            entity = Entity(
                entity_type=candidate.entity_type,
                display_label=candidate.label,
                normalized_label=candidate.normalized_label,
            )
            db.add(entity)
            db.flush()

        relationship = (
            db.execute(
                select(Relationship).where(
                    Relationship.source_version_id == version_id,
                    Relationship.object_entity_id == entity.id,
                    Relationship.relation_type == RelationType.MENTIONS.value,
                )
            )
            .scalars()
            .first()
        )
        if relationship is None:
            relationship = Relationship(
                source_version_id=version_id,
                object_entity_id=entity.id,
                relation_type=RelationType.MENTIONS.value,
                kind=RelationKind.SOURCE_SUPPORTED.value,
                origin=RelationOrigin.RULE.value,
                producer_revision=candidate.producer_revision,
            )
            db.add(relationship)
            db.flush()

        chunk = (
            db.execute(
                select(SourceChunk).where(
                    SourceChunk.version_id == version_id,
                    SourceChunk.ordinal == candidate.chunk_ordinal,
                )
            )
            .scalars()
            .first()
        )
        if chunk is None:
            raise InvalidChunkSet(
                f"chunk {candidate.chunk_ordinal} is not stored for {version_id}; "
                "store the chunks before the relations that cite them"
            )

        db.execute(
            delete(RelationshipEvidence).where(
                RelationshipEvidence.relationship_id == relationship.id
            )
        )
        db.add(
            RelationshipEvidence(
                relationship_id=relationship.id,
                chunk_id=chunk.id,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                quote=candidate.quote,
            )
        )
        written += 1

    db.commit()
    return written
