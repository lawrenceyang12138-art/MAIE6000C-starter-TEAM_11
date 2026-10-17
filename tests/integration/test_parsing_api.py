"""HTTP contract for B's files, evidence, relations and review handlers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import FileRecord, FileVersion, SourceChunk
from services.parsing.chunking import Chunk, chunk_document
from services.parsing.pdf import extract_document, file_identity
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations

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
            "relative_path": "reports-aaaaaaaa/invoice.pdf",
            "presence_status": "present",
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
            "source_path": "reports-aaaaaaaa/invoice.pdf",
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
    relationship_id = relations.json()[0]["relationship_id"]

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
