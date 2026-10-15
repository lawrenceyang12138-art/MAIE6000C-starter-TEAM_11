"""Tests for the bounded relation read and the append-only review.

The interesting behaviour is the revision guard: a decision taken against a
stale view must be refused, not silently applied over someone else's.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import Review, ReviewDecision
from services.parsing.chunking import chunk_document
from services.parsing.graph import (
    MAX_RELATIONSHIPS,
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
