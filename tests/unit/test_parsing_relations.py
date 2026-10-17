"""Tests for the rule-based entity candidate finder.

The fixture is synthetic and contains one of each entity type on purpose:
a project name, a titled person, and a topic that recurs across pages.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import Entity, Relationship, RelationshipEvidence, SourceChunk
from services.parsing.chunking import Chunk, chunk_document
from services.parsing.pdf import extract_document, file_identity
from services.parsing.persist import (
    InvalidChunkSet,
    InvalidRelationEvidence,
    persist_chunks,
    persist_relations,
)
from services.parsing.relations import (
    ENTITY_PERSON,
    ENTITY_PROJECT,
    ENTITY_TOPIC,
    MAX_CANDIDATES,
    PRODUCER_REVISION,
    CandidateRelation,
    candidate_relations,
    find_mentions,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "relations"


def _chunks():
    return chunk_document(extract_document(FIXTURES / "entities.pdf"))


def test_candidates_include_all_three_entity_types():
    candidates = candidate_relations(_chunks())

    found = {candidate.entity_type for candidate in candidates}
    assert ENTITY_PROJECT in found, "project name was not found"
    assert ENTITY_PERSON in found, "titled person was not found"
    assert ENTITY_TOPIC in found, "recurring topic was not found"


def test_project_name_is_found_and_located():
    candidates = candidate_relations(_chunks())
    projects = [c for c in candidates if c.entity_type == ENTITY_PROJECT]

    assert projects, "no project candidate"
    project = projects[0]
    assert project.label == "File Management Assistant"
    assert project.normalized_label == "file management assistant"
    assert project.page_number == 1


def test_titled_person_is_found():
    candidates = candidate_relations(_chunks())
    people = [c for c in candidates if c.entity_type == ENTITY_PERSON]

    assert people, "no person candidate"
    assert any(person.normalized_label == "chen" for person in people)


def test_recurring_topic_is_found():
    candidates = candidate_relations(_chunks())
    topics = [c for c in candidates if c.entity_type == ENTITY_TOPIC]

    assert any(topic.normalized_label == "schema design" for topic in topics)


def test_every_candidate_carries_page_and_quote():
    chunks = _chunks()
    by_ordinal = {chunk.ordinal: chunk for chunk in chunks}

    for candidate in candidate_relations(chunks):
        chunk = by_ordinal[candidate.chunk_ordinal]
        # The offset must point at the label inside the chunk it came from.
        assert chunk.text[candidate.start_offset : candidate.end_offset] == candidate.label
        # The page must be the page of that chunk, not a guess.
        assert candidate.page_number == chunk.page_number
        # The quote must be real text from the chunk.
        assert candidate.quote
        assert candidate.label in candidate.quote
        assert candidate.producer_revision == PRODUCER_REVISION


def test_candidates_are_deduplicated_to_one_row_per_entity():
    chunks = _chunks()
    candidates = candidate_relations(chunks)
    mentions = find_mentions(chunks)

    keys = [(c.entity_type, c.normalized_label) for c in candidates]
    assert len(keys) == len(set(keys)), "an entity was emitted twice"
    # The project is mentioned on both pages, so there are more mentions than
    # candidates - which is the point of keeping only the first.
    assert len(mentions) >= len(candidates)


def test_the_candidate_list_stays_bounded_even_when_more_are_asked_for():
    """The schedule's point is a bounded candidate list, not a graph."""
    chunks = [
        Chunk(
            ordinal=index,
            page_number=index,
            text=f"{chr(65 + index)}q Project was chosen\nsecond line of the page",
        )
        for index in range(20)
    ]

    assert len(find_mentions(chunks)) > MAX_CANDIDATES, "the fixture is too small"
    assert len(candidate_relations(chunks, limit=1000)) == MAX_CANDIDATES


def test_sentence_openers_are_not_treated_as_names():
    candidates = candidate_relations(_chunks())
    labels = {candidate.normalized_label for candidate in candidates}

    # "The" and "Notes" begin sentences and must not become entities.
    assert "the" not in labels
    assert "notes page" not in labels


def test_relations_are_stored_with_their_evidence(
    db_session: Session, make_file_version
):
    real_hash, _ = file_identity(FIXTURES / "entities.pdf")
    version_id = make_file_version(sha256=real_hash)
    chunks = _chunks()
    persist_chunks(db_session, version_id, chunks)

    written = persist_relations(db_session, version_id, candidate_relations(chunks))

    assert written >= 3
    relationships = (
        db_session.execute(
            select(Relationship).where(Relationship.source_version_id == version_id)
        )
        .scalars()
        .all()
    )
    entities = {row.id: row for row in db_session.execute(select(Entity)).scalars()}
    types = {entities[row.object_entity_id].entity_type for row in relationships}
    assert {"person", "project", "topic"} <= types

    for relationship in relationships:
        evidence = (
            db_session.execute(
                select(RelationshipEvidence).where(
                    RelationshipEvidence.relationship_id == relationship.id
                )
            )
            .scalars()
            .all()
        )
        assert evidence, "a relationship without evidence must not be stored"
        for row in evidence:
            chunk = db_session.get(SourceChunk, row.chunk_id)
            assert chunk.text[row.start_offset : row.end_offset] in row.quote


def test_storing_relations_twice_does_not_duplicate_them(
    db_session: Session, make_file_version
):
    real_hash, _ = file_identity(FIXTURES / "entities.pdf")
    version_id = make_file_version(sha256=real_hash)
    chunks = _chunks()
    persist_chunks(db_session, version_id, chunks)
    candidates = candidate_relations(chunks)

    persist_relations(db_session, version_id, candidates)
    first_ids = {r.id for r in db_session.execute(select(Relationship)).scalars()}
    persist_relations(db_session, version_id, candidates)
    second_ids = {r.id for r in db_session.execute(select(Relationship)).scalars()}

    assert first_ids == second_ids, "re-running must not create new relationships"
    assert len(second_ids) == len(candidates)


def test_two_mentions_of_one_entity_keep_two_evidence_rows(
    db_session: Session, make_file_version
):
    """One relationship can be supported by more than one passage.

    Replacing the evidence set once per relationship and then adding every
    candidate avoids the old bug where each mention deleted the previous one.
    """
    version_id = make_file_version(sha256="6" * 64)
    first_text = "Alpha Project appears first."
    second_text = "Later, Alpha Project appears again."
    persist_chunks(
        db_session,
        version_id,
        [
            Chunk(ordinal=1, page_number=1, text=first_text),
            Chunk(ordinal=2, page_number=2, text=second_text),
        ],
    )
    candidates = [
        CandidateRelation(
            entity_type=ENTITY_PROJECT,
            label="Alpha Project",
            normalized_label="alpha project",
            chunk_ordinal=1,
            page_number=1,
            start_offset=0,
            end_offset=len("Alpha Project"),
            quote=first_text,
        ),
        CandidateRelation(
            entity_type=ENTITY_PROJECT,
            label="Alpha Project",
            normalized_label="alpha project",
            chunk_ordinal=2,
            page_number=2,
            start_offset=len("Later, "),
            end_offset=len("Later, Alpha Project"),
            quote=second_text,
        ),
    ]

    written = persist_relations(db_session, version_id, candidates)

    relationships = db_session.execute(select(Relationship)).scalars().all()
    evidence = db_session.execute(select(RelationshipEvidence)).scalars().all()
    assert written == 2
    assert len(relationships) == 1
    assert len(evidence) == 2


def test_a_rerun_updates_the_producer_revision(
    db_session: Session, make_file_version
):
    """An existing relationship must not keep crediting an older rule set."""
    version_id = make_file_version(sha256="5" * 64)
    text = "Alpha Project was approved."
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text=text)],
    )
    candidate = CandidateRelation(
        entity_type=ENTITY_PROJECT,
        label="Alpha Project",
        normalized_label="alpha project",
        chunk_ordinal=1,
        page_number=1,
        start_offset=0,
        end_offset=len("Alpha Project"),
        quote=text,
        producer_revision="rules-v1",
    )
    persist_relations(db_session, version_id, [candidate])

    candidate = CandidateRelation(
        entity_type=ENTITY_PROJECT,
        label="Alpha Project",
        normalized_label="alpha project",
        chunk_ordinal=1,
        page_number=1,
        start_offset=0,
        end_offset=len("Alpha Project"),
        quote=text,
        producer_revision="rules-v2",
    )
    persist_relations(db_session, version_id, [candidate])

    relationship = db_session.execute(select(Relationship)).scalars().one()
    assert relationship.producer_revision == "rules-v2"


def test_evidence_needs_the_chunks_to_be_stored_first(
    db_session: Session, make_file_version
):
    version_id = make_file_version(sha256="9" * 64)
    chunks = _chunks()

    with pytest.raises(InvalidChunkSet):
        persist_relations(db_session, version_id, candidate_relations(chunks))


def test_a_failed_relation_batch_leaves_no_partial_rows(
    db_session: Session, make_file_version
):
    """A later bad candidate must not leave an earlier one waiting to be saved.

    ``persist_relations`` owns its transaction. Without a rollback, a caller
    that later commits the same session would silently persist the valid prefix
    even though the function reported failure.
    """
    version_id = make_file_version(sha256="8" * 64)
    text = "Alpha Project was approved."
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text=text)],
    )

    valid = CandidateRelation(
        entity_type=ENTITY_PROJECT,
        label="Alpha Project",
        normalized_label="alpha project",
        chunk_ordinal=1,
        page_number=1,
        start_offset=0,
        end_offset=len("Alpha Project"),
        quote=text,
    )
    missing_chunk = CandidateRelation(
        entity_type=ENTITY_PROJECT,
        label="Beta Project",
        normalized_label="beta project",
        chunk_ordinal=2,
        page_number=2,
        start_offset=0,
        end_offset=len("Beta Project"),
        quote="Beta Project was rejected.",
    )

    with pytest.raises(InvalidChunkSet):
        persist_relations(db_session, version_id, [valid, missing_chunk])

    # This commit is deliberate: it would save any rows the failed function
    # forgot to roll back.
    db_session.commit()
    assert db_session.execute(select(Entity)).scalars().all() == []
    assert db_session.execute(select(Relationship)).scalars().all() == []
    assert db_session.execute(select(RelationshipEvidence)).scalars().all() == []


def test_relation_evidence_must_point_at_the_quoted_label(
    db_session: Session, make_file_version
):
    """A quote is useful only when its offsets identify the label in the chunk."""
    version_id = make_file_version(sha256="7" * 64)
    text = "Alpha Project was approved."
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text=text)],
    )
    malformed = CandidateRelation(
        entity_type=ENTITY_PROJECT,
        label="Alpha Project",
        normalized_label="alpha project",
        chunk_ordinal=1,
        page_number=1,
        start_offset=len(text) + 10,
        end_offset=len(text) + 23,
        quote="Alpha Project was approved.",
    )

    with pytest.raises(InvalidRelationEvidence):
        persist_relations(db_session, version_id, [malformed])

    db_session.commit()
    assert db_session.execute(select(Entity)).scalars().all() == []
    assert db_session.execute(select(Relationship)).scalars().all() == []
    assert db_session.execute(select(RelationshipEvidence)).scalars().all() == []
