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
    EntityType,
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


class InvalidRelationEvidence(ValueError):
    """A candidate's quote or offsets do not describe the stored chunk."""


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
    # A replacement stores the whole chunk set for a version, so a hole means
    # the caller is writing a partial set under the name of a full one. Every
    # way of counting passages ("chunk 3 of 7", the next ordinal, a coverage
    # check) then describes a document that does not exist.
    if set(ordinals) != set(range(1, len(ordinals) + 1)):
        raise InvalidChunkSet("chunk ordinals must run 1..N with no gaps")


def persist_chunks(
    db: Session,
    version_id: str,
    chunks: Sequence[Chunk],
    *,
    commit: bool = True,
) -> int:
    """Replace the stored chunks of ``version_id`` with ``chunks``.

    Returns the number of chunks written. The whole replace is one
    transaction: on any failure the previous chunks are left untouched and the
    exception is re-raised for the caller to record against the job. Passing
    ``commit=False`` flushes the replacement but leaves the final commit to an
    orchestrating caller that also needs to publish the version status.

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

        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        # Undo the delete along with the partial insert.
        db.rollback()
        raise

    return len(chunks)


def _validate_relation_candidates(
    candidates: Sequence[CandidateRelation],
    chunks_by_ordinal: dict[int, SourceChunk],
) -> None:
    """Reject malformed evidence before the transaction writes anything."""
    entity_types = {entity_type.value for entity_type in EntityType}

    for candidate in candidates:
        chunk = chunks_by_ordinal.get(candidate.chunk_ordinal)
        if chunk is None:
            raise InvalidChunkSet(
                f"chunk {candidate.chunk_ordinal} is not stored; "
                "store the chunks before the relations that cite them"
            )

        if candidate.entity_type not in entity_types:
            raise InvalidRelationEvidence(
                f"unknown entity type {candidate.entity_type!r}"
            )
        if candidate.normalized_label != " ".join(candidate.label.split()).casefold():
            raise InvalidRelationEvidence(
                f"normalized label {candidate.normalized_label!r} does not match "
                f"label {candidate.label!r}"
            )
        if candidate.page_number != chunk.page_number:
            raise InvalidRelationEvidence(
                f"candidate page {candidate.page_number} does not match stored "
                f"page {chunk.page_number}"
            )
        if not (
            0
            <= candidate.start_offset
            < candidate.end_offset
            <= len(chunk.text)
        ):
            raise InvalidRelationEvidence(
                f"offsets {candidate.start_offset}:{candidate.end_offset} are "
                f"outside the stored chunk"
            )
        if chunk.text[candidate.start_offset : candidate.end_offset] != candidate.label:
            raise InvalidRelationEvidence(
                "candidate offsets do not point at the label in the stored chunk"
            )
        if not candidate.quote.strip() or candidate.label not in candidate.quote:
            raise InvalidRelationEvidence(
                "the quote does not contain the label it is supposed to support"
            )


def persist_relations(
    db: Session,
    version_id: str,
    candidates: Sequence[CandidateRelation],
    *,
    commit: bool = True,
) -> int:
    """Store entity candidates and the evidence that supports each one.

    Entities and relationships are found-or-created rather than replaced, so a
    relationship keeps its row id across re-runs. That matters later: a human
    review points at a relationship, and replacing the row would silently throw
    the review away.

    Evidence rows are refreshed for each relationship, because they carry
    offsets into chunk text and a parser change moves them.

    The chunks must already be stored: evidence is attached to a stored chunk,
    and the chunk is resolved by its ordinal within this version. Passing
    ``commit=False`` flushes the candidate batch so it can share the parsing
    handler's final transaction.
    """
    written = 0
    try:
        chunks_by_ordinal = {
            chunk.ordinal: chunk
            for chunk in db.execute(
                select(SourceChunk).where(SourceChunk.version_id == version_id)
            )
            .scalars()
            .all()
        }
        _validate_relation_candidates(candidates, chunks_by_ordinal)

        refreshed_relationships: set[str] = set()
        evidence_keys: set[tuple[str, str, int, int]] = set()
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
            else:
                # A re-run under a newer rule set must not keep claiming that
                # an old producer made the same relationship.
                relationship.producer_revision = candidate.producer_revision

            if relationship.id not in refreshed_relationships:
                db.execute(
                    delete(RelationshipEvidence).where(
                        RelationshipEvidence.relationship_id == relationship.id
                    )
                )
                refreshed_relationships.add(relationship.id)

            chunk = chunks_by_ordinal[candidate.chunk_ordinal]
            evidence_key = (
                relationship.id,
                chunk.id,
                candidate.start_offset,
                candidate.end_offset,
            )
            if evidence_key in evidence_keys:
                continue
            evidence_keys.add(evidence_key)
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

        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        # Validation failures and database errors must leave the whole batch
        # unwritten, not a valid prefix waiting for a caller's later commit.
        db.rollback()
        raise
    return written
