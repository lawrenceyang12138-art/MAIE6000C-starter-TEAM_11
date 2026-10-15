"""Tests for the bounded relation read and the append-only review.

The interesting behaviour is the revision guard: a decision taken against a
stale view must be refused, not silently applied over someone else's.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import Entity, RelationshipEvidence, Review, ReviewDecision
from services.parsing import graph
from services.parsing.chunking import Chunk, chunk_document
from services.parsing.graph import (
    MAX_RELATIONSHIPS,
    REASON_CORRECTED_ENTITY_NOT_FOUND,
    REASON_CORRECTION_TARGET_NOT_ALLOWED,
    REASON_CORRECTION_WITHOUT_TARGET,
    REASON_INVALID_DECISION,
    REASON_RELATIONSHIP_NOT_FOUND,
    REASON_REVIEW_CONFLICT,
    ReviewRefused,
    read_relationships,
    record_review,
)
from services.parsing.pdf import extract_document, file_identity
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "relations"


def _version_with_relations(db: Session, make_file_version) -> str:
    real_hash, _ = file_identity(FIXTURES / "entities.pdf")
    version_id = make_file_version(sha256=real_hash)
    chunks = chunk_document(extract_document(FIXTURES / "entities.pdf"))
    persist_chunks(db, version_id, chunks)
    persist_relations(db, version_id, candidate_relations(chunks))
    return version_id


def _an_entity_id_other_than(db: Session, label: str) -> str:
    """A real entity the reviewer could point at instead of ``label``."""
    entity = (
        db.execute(select(Entity).where(Entity.display_label != label).limit(1))
        .scalars()
        .first()
    )
    assert entity is not None, "fixture has no second entity to correct towards"
    return entity.id


def test_relations_are_read_back_with_their_evidence(
    db_session: Session, make_file_version
):
    version_id = _version_with_relations(db_session, make_file_version)

    views = read_relationships(db_session, version_id)

    assert views, "no relations were read back"
    for view in views:
        assert view.quote, "a relation was served without its evidence"
        assert view.page_number is not None
        assert view.origin == "rule"
        assert view.producer_revision
        assert view.decision is None
        assert view.decision_revision == 0


def test_a_relation_whose_passage_was_replaced_says_so(
    db_session: Session, make_file_version
):
    """Re-processing a version can leave a relation without its passage.

    The relation and its human reviews survive a re-parse; the chunk it cited
    may not. That used to surface as an empty quote, which reads like a display
    bug rather than a fact about the data.
    """
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]
    assert view.evidence_missing is False
    assert view.quote

    # A different parser revision produces a different chunk set.
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="a completely different passage")],
    )

    refreshed = read_relationships(db_session, version_id)
    assert refreshed, "re-processing must not delete the relation rows"
    assert all(other.evidence_missing for other in refreshed)
    assert all(other.quote == "" for other in refreshed)


def test_rerunning_the_relation_step_restores_the_evidence(
    db_session: Session, make_file_version
):
    """This is what the pipeline should do after re-processing a version.

    It also pins a database behaviour the suite could not see before: the
    evidence rows are removed by ON DELETE CASCADE, which PostgreSQL enforces
    and SQLite only enforces with foreign keys switched on. Without that, the
    rows were left dangling and the other assertions still passed - green
    tests over an unverified behaviour.
    """
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    assert (
        db_session.execute(select(RelationshipEvidence)).scalars().all()
    ), "the fixture stored no evidence to begin with"

    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="a completely different passage")],
    )
    assert read_relationships(db_session, version_id)[0].evidence_missing

    db_session.expire_all()
    assert (
        db_session.execute(select(RelationshipEvidence)).scalars().all() == []
    ), "evidence citing a replaced chunk must be removed, not left dangling"

    chunks = chunk_document(extract_document(FIXTURES / "entities.pdf"))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))

    refreshed = {
        candidate.relationship_id: candidate
        for candidate in read_relationships(db_session, version_id)
    }
    assert refreshed[view.relationship_id].evidence_missing is False
    assert refreshed[view.relationship_id].quote


def test_relation_read_is_bounded(db_session: Session, make_file_version):
    version_id = _version_with_relations(db_session, make_file_version)

    # Asking for more than the cap must not return more than the cap.
    assert len(read_relationships(db_session, version_id, limit=1000)) <= (
        MAX_RELATIONSHIPS
    )
    assert read_relationships(db_session, version_id, limit=0) == []


def test_first_review_is_revision_one(db_session: Session, make_file_version):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    revision = record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=view.decision_revision,
        actor="reviewer-a",
    )

    assert revision == 1
    refreshed = {v.relationship_id: v for v in read_relationships(db_session, version_id)}
    assert refreshed[view.relationship_id].decision == "confirmed"
    assert refreshed[view.relationship_id].decision_revision == 1


def test_two_reviewers_writing_the_same_revision_collide_cleanly(
    db_session: Session, make_file_version, monkeypatch
):
    """The guard reads and then writes, so it cannot stop two interleaved
    requests on its own. The unique constraint does - and the caller should see
    the same conflict it sees when the guard fires, not a database error."""
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=0,
        actor="reviewer-a",
    )

    # A second request read the revision before the first one committed.
    monkeypatch.setattr(graph, "effective_decision", lambda db, rid: (None, 0))

    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            view.relationship_id,
            ReviewDecision.REJECTED.value,
            expected_revision=0,
            actor="reviewer-b",
        )

    assert excinfo.value.reason_code == REASON_REVIEW_CONFLICT

    stored = (
        db_session.execute(
            select(Review).where(Review.relationship_id == view.relationship_id)
        )
        .scalars()
        .all()
    )
    assert [row.decision_revision for row in stored] == [1]
    assert stored[0].decision == "confirmed", "the first decision must stand"


def test_a_stale_revision_is_refused_rather_than_overwritten(
    db_session: Session, make_file_version
):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=0,
        actor="reviewer-a",
    )

    # Reviewer B is still looking at revision 0.
    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            view.relationship_id,
            ReviewDecision.REJECTED.value,
            expected_revision=0,
            actor="reviewer-b",
        )

    assert excinfo.value.reason_code == REASON_REVIEW_CONFLICT
    # Reviewer A's decision must still be the effective one.
    refreshed = {v.relationship_id: v for v in read_relationships(db_session, version_id)}
    assert refreshed[view.relationship_id].decision == "confirmed"


def test_reviews_are_append_only(db_session: Session, make_file_version):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=0,
    )
    revision = record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.REJECTED.value,
        expected_revision=1,
        reason="not actually the same project",
    )

    assert revision == 2
    rows = (
        db_session.execute(
            select(Review)
            .where(Review.relationship_id == view.relationship_id)
            .order_by(Review.decision_revision)
        )
        .scalars()
        .all()
    )
    # Both decisions are kept; the earlier one is history, not garbage.
    assert [row.decision for row in rows] == ["confirmed", "rejected"]
    assert [row.decision_revision for row in rows] == [1, 2]


def test_an_invalid_decision_is_refused(db_session: Session, make_file_version):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    with pytest.raises(ReviewRefused) as excinfo:
        record_review(db_session, view.relationship_id, "maybe", expected_revision=0)

    assert excinfo.value.reason_code == REASON_INVALID_DECISION
    assert (
        db_session.execute(
            select(Review).where(Review.relationship_id == view.relationship_id)
        )
        .scalars()
        .all()
        == []
    )


def test_reviewing_an_unknown_relationship_is_refused(db_session: Session):
    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            "00000000-0000-0000-0000-000000000000",
            ReviewDecision.CONFIRMED.value,
            expected_revision=0,
        )

    assert excinfo.value.reason_code == REASON_RELATIONSHIP_NOT_FOUND


def test_all_three_decision_types_are_recorded_independently(
    db_session: Session, make_file_version
):
    """The check the schedule asks for: one of each decision, two rejections."""
    version_id = _version_with_relations(db_session, make_file_version)
    views = read_relationships(db_session, version_id)
    assert len(views) >= 3, "need three relations to record three decisions"

    first, second, third = views[0], views[1], views[2]

    record_review(
        db_session,
        first.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=0,
        actor="reviewer-a",
    )
    record_review(
        db_session,
        second.relationship_id,
        ReviewDecision.CORRECTED.value,
        expected_revision=0,
        reason="label should be the full name",
        actor="reviewer-a",
        corrected_entity_id=_an_entity_id_other_than(db_session, second.label),
    )
    record_review(
        db_session,
        third.relationship_id,
        ReviewDecision.REJECTED.value,
        expected_revision=0,
        reason="not an entity",
        actor="reviewer-b",
    )
    # A second rejection, on a relation already confirmed, taken with the
    # revision the reviewer actually saw.
    record_review(
        db_session,
        first.relationship_id,
        ReviewDecision.REJECTED.value,
        expected_revision=1,
        reason="changed my mind",
        actor="reviewer-b",
    )

    effective = {v.relationship_id: v for v in read_relationships(db_session, version_id)}
    assert effective[first.relationship_id].decision == "rejected"
    assert effective[first.relationship_id].decision_revision == 2
    assert effective[second.relationship_id].decision == "corrected"
    assert effective[third.relationship_id].decision == "rejected"

    # Both rejections, the confirmation and the correction are all still stored.
    decisions = [
        row.decision
        for row in db_session.execute(
            select(Review).order_by(Review.relationship_id, Review.decision_revision)
        )
        .scalars()
        .all()
    ]
    assert decisions.count("rejected") == 2
    assert "confirmed" in decisions
    assert "corrected" in decisions


def test_a_correction_keeps_what_the_reviewer_said_instead(
    db_session: Session, make_file_version
):
    """A correction is only useful if it names the replacement."""
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]
    replacement = _an_entity_id_other_than(db_session, view.label)

    record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CORRECTED.value,
        expected_revision=0,
        reason="this relation points at the wrong project",
        actor="reviewer-a",
        corrected_entity_id=replacement,
    )

    stored = (
        db_session.execute(
            select(Review).where(Review.relationship_id == view.relationship_id)
        )
        .scalars()
        .one()
    )
    assert stored.decision == "corrected"
    assert stored.corrected_entity_id == replacement

    refreshed = {v.relationship_id: v for v in read_relationships(db_session, version_id)}
    assert refreshed[view.relationship_id].corrected_entity_id == replacement

    # A later confirmation clears the pointer: the review is append-only, so
    # the correction stays in history while the effective one moves on.
    record_review(
        db_session,
        view.relationship_id,
        ReviewDecision.CONFIRMED.value,
        expected_revision=1,
        actor="reviewer-b",
    )
    refreshed = {v.relationship_id: v for v in read_relationships(db_session, version_id)}
    assert refreshed[view.relationship_id].decision == "confirmed"
    assert refreshed[view.relationship_id].corrected_entity_id is None


def test_a_correction_without_a_target_is_refused(
    db_session: Session, make_file_version
):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            view.relationship_id,
            ReviewDecision.CORRECTED.value,
            expected_revision=0,
            reason="wrong, but the reviewer did not say what it should be",
        )

    assert excinfo.value.reason_code == REASON_CORRECTION_WITHOUT_TARGET
    assert (
        db_session.execute(
            select(Review).where(Review.relationship_id == view.relationship_id)
        )
        .scalars()
        .all()
        == []
    )


def test_only_a_correction_may_name_a_replacement(
    db_session: Session, make_file_version
):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]
    replacement = _an_entity_id_other_than(db_session, view.label)

    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            view.relationship_id,
            ReviewDecision.CONFIRMED.value,
            expected_revision=0,
            actor="reviewer-a",
            corrected_entity_id=replacement,
        )

    assert excinfo.value.reason_code == REASON_CORRECTION_TARGET_NOT_ALLOWED


def test_a_correction_to_an_entity_that_does_not_exist_is_refused(
    db_session: Session, make_file_version
):
    version_id = _version_with_relations(db_session, make_file_version)
    view = read_relationships(db_session, version_id)[0]

    with pytest.raises(ReviewRefused) as excinfo:
        record_review(
            db_session,
            view.relationship_id,
            ReviewDecision.CORRECTED.value,
            expected_revision=0,
            corrected_entity_id="00000000-0000-0000-0000-000000000000",
        )

    assert excinfo.value.reason_code == REASON_CORRECTED_ENTITY_NOT_FOUND
