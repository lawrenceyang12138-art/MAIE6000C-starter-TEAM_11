"""HTTP contract for B's files, evidence, relations and review handlers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    Entity,
    FileRecord,
    FileVersion,
    Review,
    RelationshipEvidence,
    RootStatus,
    SourceChunk,
)
from services.parsing.chunking import Chunk, chunk_document
from services.parsing.pdf import extract_document, file_identity
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations
from services.scan.handler import resolve_source_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _current_version(
    db: Session, make_file_version, sha256: str = "a" * 64
) -> tuple[str, str, str]:
    version_id = make_file_version(sha256=sha256)
    version = db.get(FileVersion, version_id)
    file_record = db.get(FileRecord, version.file_id)
    file_record.current_version_id = version_id
    db.commit()
    return version_id, file_record.id, file_record.root_id


def test_file_list_and_evidence_use_the_same_current_chunk(
    client, db_session: Session, make_file_version
):
    version_id, file_id, root_id = _current_version(db_session, make_file_version)
    persist_chunks(
        db_session,
        version_id,
        [
            Chunk(ordinal=1, page_number=3, text="the current passage"),
        ],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()

    files = client.get("/files", params={"root_id": root_id})
    assert files.status_code == 200
    assert files.json() == [
        {
            "file_id": file_id,
            "root_id": root_id,
            "version_id": version_id,
            "display_name": "invoice.pdf",
            "relative_path": "invoice.pdf",
            "presence_status": "present",
            "presence_reason": None,
            "status": "discovered",
            "error_code": None,
            "updated_at": files.json()[0]["updated_at"],
        }
    ]

    evidence = client.get(f"/evidence/{chunk.id}")
    assert evidence.status_code == 200
    payload = evidence.json()
    assert payload["file_id"] == file_id
    assert payload["version_id"] == version_id
    assert payload["page_number"] == 3
    assert payload["ordinal"] == 1
    assert payload["text"] == "the current passage"

    file_evidence = client.get(
        f"/files/{file_id}/evidence",
        params={"version_id": version_id},
    )
    assert file_evidence.status_code == 200
    assert file_evidence.json() == [
        {
            "file_id": file_id,
            "version_id": version_id,
            "page": 3,
            "source_path": "invoice.pdf",
            "excerpt": "the current passage",
            "evidence_id": chunk.id,
        }
    ]


def test_stale_evidence_returns_a_structured_conflict(
    client, db_session: Session, make_file_version
):
    version_id, _, _ = _current_version(db_session, make_file_version, "b" * 64)
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="historical passage")],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()
    version = db_session.get(FileVersion, version_id)
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.current_version_id = "11111111-1111-1111-1111-111111111111"
    db_session.commit()

    response = client.get(f"/evidence/{chunk.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_superseded"


def test_modified_source_returns_a_structured_conflict_without_a_rescan(
    client, db_session: Session, make_file_version
):
    version_id, _, _ = _current_version(db_session, make_file_version, "m" * 64)
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="stale after an external edit")],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()
    source_path = resolve_source_path(db_session, version_id, for_write=False)
    source_path.write_bytes(source_path.read_bytes() + b"external edit")

    response = client.get(f"/evidence/{chunk.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_changed"


def test_deleted_source_returns_not_found_without_a_rescan(
    client, db_session: Session, make_file_version
):
    version_id, _, _ = _current_version(db_session, make_file_version, "z" * 64)
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="stale after an external move")],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()
    resolve_source_path(db_session, version_id, for_write=False).unlink()

    response = client.get(f"/evidence/{chunk.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_missing"


def test_evidence_refuses_a_stored_path_that_escapes_its_mount(
    client, db_session: Session, make_file_version
):
    version_id, _, _ = _current_version(db_session, make_file_version, "e" * 64)
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="must not leak from outside")],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()
    version = db_session.get(FileVersion, version_id)
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.relative_path = "../outside.pdf"
    db_session.commit()

    response = client.get(f"/evidence/{chunk.id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_out_of_scope"


def test_evidence_refuses_a_revoked_root(
    client, db_session: Session, make_file_version
):
    version_id, _, root_id = _current_version(db_session, make_file_version, "v" * 64)
    persist_chunks(
        db_session,
        version_id,
        [Chunk(ordinal=1, page_number=1, text="no longer authorized")],
    )
    chunk = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version_id)
    ).scalars().one()
    root = db_session.get(AuthorizedRoot, root_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    response = client.get(f"/evidence/{chunk.id}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "root_revoked"


def test_file_evidence_missing_file_is_404_and_revoked_root_is_hidden(
    client, db_session: Session, make_file_version
):
    version_id, file_id, root_id = _current_version(db_session, make_file_version, "d" * 64)
    missing = client.get(
        "/files/does-not-exist/evidence",
        params={"version_id": version_id},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "file_missing"

    root = db_session.get(AuthorizedRoot, root_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    assert client.get("/files", params={"root_id": root_id}).json() == []


def test_relation_read_and_review_conflict_are_reachable_over_http(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, _ = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))

    relations = client.get(f"/versions/{version_id}/relations")
    assert relations.status_code == 200
    assert len(relations.json()) >= 3
    first_relation = relations.json()[0]
    relationship_id = first_relation["relationship_id"]
    evidence = client.get(f"/evidence/{first_relation['chunk_id']}")
    assert evidence.status_code == 200
    assert evidence.json()["version_id"] == version_id
    assert evidence.json()["page_number"] == first_relation["page_number"]
    assert first_relation["quote"].split()[0] in evidence.json()["text"]

    first = client.post(
        f"/relations/{relationship_id}/reviews",
        json={
            "decision": "confirmed",
            "expected_revision": 0,
            "actor": "reviewer-a",
        },
    )
    assert first.status_code == 200
    assert first.json()["decision_revision"] == 1

    stale = client.post(
        f"/relations/{relationship_id}/reviews",
        json={
            "decision": "rejected",
            "expected_revision": 0,
            "actor": "reviewer-b",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "review_conflict"


def test_confirm_correct_and_reject_are_appended_to_review_history(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, _ = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))

    relations = client.get(f"/versions/{version_id}/relations").json()[:3]
    replacement = db_session.execute(
        select(Entity).where(Entity.display_label != relations[1]["label"])
    ).scalars().first()
    assert replacement is not None

    payloads = [
        {"decision": "confirmed", "expected_revision": 0, "actor": "reviewer-a"},
        {
            "decision": "corrected",
            "expected_revision": 0,
            "actor": "reviewer-a",
            "reason": "wrong entity",
            "corrected_entity_id": replacement.id,
        },
        {
            "decision": "rejected",
            "expected_revision": 0,
            "actor": "reviewer-b",
            "reason": "not an entity",
        },
    ]
    for relation, payload in zip(relations, payloads, strict=True):
        response = client.post(
            f"/relations/{relation['relationship_id']}/reviews",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["decision_revision"] == 1

    db_session.expire_all()
    history = db_session.execute(
        select(Review).order_by(Review.created_at, Review.decision_revision)
    ).scalars().all()
    assert {row.decision for row in history} == {"confirmed", "corrected", "rejected"}


def test_relation_read_and_review_refuse_a_modified_source(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, _ = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))
    relationship = client.get(f"/versions/{version_id}/relations").json()[0]
    source_path = resolve_source_path(db_session, version_id, for_write=False)
    source_path.write_bytes(source_path.read_bytes() + b"external edit")

    relations = client.get(f"/versions/{version_id}/relations")
    review = client.post(
        f"/relations/{relationship['relationship_id']}/reviews",
        json={"decision": "confirmed", "expected_revision": 0},
    )

    assert relations.status_code == 409
    assert relations.json()["detail"]["code"] == "source_changed"
    assert review.status_code == 409
    assert review.json()["detail"]["code"] == "source_changed"


def test_relation_read_and_review_refuse_a_revoked_root(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, root_id = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))
    relationship = client.get(f"/versions/{version_id}/relations").json()[0]
    root = db_session.get(AuthorizedRoot, root_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    relations = client.get(f"/versions/{version_id}/relations")
    review = client.post(
        f"/relations/{relationship['relationship_id']}/reviews",
        json={"decision": "rejected", "expected_revision": 0},
    )

    assert relations.status_code == 403
    assert relations.json()["detail"]["code"] == "root_revoked"
    assert review.status_code == 403
    assert review.json()["detail"]["code"] == "root_revoked"


def test_historical_version_relation_read_and_review_are_refused(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, _ = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))
    relationship = client.get(f"/versions/{version_id}/relations").json()[0]
    version = db_session.get(FileVersion, version_id)
    file_record = db_session.get(FileRecord, version.file_id)
    file_record.current_version_id = "11111111-1111-1111-1111-111111111111"
    db_session.commit()

    relations = client.get(f"/versions/{version_id}/relations")
    review = client.post(
        f"/relations/{relationship['relationship_id']}/reviews",
        json={"decision": "confirmed", "expected_revision": 0},
    )

    assert relations.status_code == 409
    assert relations.json()["detail"]["code"] == "version_superseded"
    assert review.status_code == 409
    assert review.json()["detail"]["code"] == "version_superseded"


def test_review_without_valid_evidence_returns_conflict(
    client, db_session: Session, make_file_version
):
    path = FIXTURES / "relations" / "entities.pdf"
    real_hash, _ = file_identity(path)
    version_id, _, _ = _current_version(db_session, make_file_version, real_hash)
    chunks = chunk_document(extract_document(path))
    persist_chunks(db_session, version_id, chunks)
    persist_relations(db_session, version_id, candidate_relations(chunks))
    relationship = client.get(f"/versions/{version_id}/relations").json()[0]
    for row in db_session.execute(
        select(RelationshipEvidence).where(
            RelationshipEvidence.relationship_id == relationship["relationship_id"]
        )
    ).scalars():
        db_session.delete(row)
    db_session.commit()

    response = client.post(
        f"/relations/{relationship['relationship_id']}/reviews",
        json={"decision": "confirmed", "expected_revision": 0},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "evidence_missing"
