"""Demonstrate the relation read and the review revision guard end to end.

Run inside the api container:

    python scripts/demo_relation_review.py tests/fixtures/relations/entities.pdf

Shows: the candidates a document produces, each with its page and quote; a
first review becoming revision 1; a second reviewer holding a stale view being
refused instead of overwriting the first; and a correction that names the
entity it points to instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

from services.common.db import get_session_factory
from services.common.models import (
    AuthorizedRoot,
    Entity,
    FilePresence,
    FileRecord,
    FileVersion,
    ReviewDecision,
    RootStatus,
)
from services.parsing.chunking import chunk_document
from services.parsing.graph import ReviewRefused, read_relationships, record_review
from services.parsing.pdf import extract_document, file_identity
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations

SCRATCH_MOUNT_ID = "demo-relation-review"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    path = Path(args[0])

    session_factory = get_session_factory()
    with session_factory() as db:
        for stale in (
            db.execute(
                select(AuthorizedRoot).where(AuthorizedRoot.mount_id == SCRATCH_MOUNT_ID)
            )
            .scalars()
            .all()
        ):
            db.delete(stale)
        db.commit()

        document = extract_document(path)
        chunks = chunk_document(document)

        root = AuthorizedRoot(
            mount_id=SCRATCH_MOUNT_ID,
            relative_path="demo",
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        db.flush()
        file_record = FileRecord(
            root_id=root.id,
            relative_path=f"demo/{path.name}",
            name=path.name,
            presence_status=FilePresence.PRESENT.value,
        )
        db.add(file_record)
        db.flush()
        sha256, byte_size = file_identity(path)
        version = FileVersion(
            file_id=file_record.id,
            content_sha256=sha256,
            byte_size=byte_size,
            status="discovered",
        )
        db.add(version)
        db.commit()

        persist_chunks(db, version.id, chunks)
        written = persist_relations(db, version.id, candidate_relations(chunks))

        print(f"document: {path.name} ({document.page_count} pages, {len(chunks)} chunks)")
        print(f"relations stored: {written}")
        print()

        views = read_relationships(db, version.id)
        for view in views:
            print(f"  [{view.entity_type:<7}] {view.label}  (page {view.page_number})")
            print(f"        {view.quote[:78]}")
        print()

        first = views[0]
        revision = record_review(
            db,
            first.relationship_id,
            ReviewDecision.CONFIRMED.value,
            expected_revision=first.decision_revision,
            actor="reviewer-a",
        )
        print(f"reviewer A confirms {first.label}: revision {revision}")

        try:
            record_review(
                db,
                first.relationship_id,
                ReviewDecision.REJECTED.value,
                expected_revision=first.decision_revision,
                actor="reviewer-b",
            )
            print("reviewer B was allowed through - the guard did not fire")
            return 1
        except ReviewRefused as exc:
            print(f"reviewer B holds a stale view and is refused: {exc.reason_code}")

        revision = record_review(
            db,
            first.relationship_id,
            ReviewDecision.REJECTED.value,
            expected_revision=revision,
            reason="not the same project",
            actor="reviewer-b",
        )
        print(f"reviewer B re-reads and rejects: revision {revision}")

        # A correction has to name the replacement. Reviewer A says the second
        # candidate points at the wrong entity and says which one is right.
        second = views[1]
        replacement = (
            db.execute(
                select(Entity).where(Entity.display_label != second.label).limit(1)
            )
            .scalars()
            .first()
        )
        if replacement is not None:
            revision = record_review(
                db,
                second.relationship_id,
                ReviewDecision.CORRECTED.value,
                expected_revision=second.decision_revision,
                reason="points at the wrong entity",
                actor="reviewer-a",
                corrected_entity_id=replacement.id,
            )
            print(
                f"reviewer A corrects {second.label} -> {replacement.display_label}:"
                f" revision {revision}"
            )

            try:
                record_review(
                    db,
                    second.relationship_id,
                    ReviewDecision.CORRECTED.value,
                    expected_revision=revision,
                    reason="corrected without saying what it should be",
                    actor="reviewer-c",
                )
                print("a correction without a target was allowed through")
                return 1
            except ReviewRefused as exc:
                print(
                    "a correction that names no replacement is refused: "
                    f"{exc.reason_code}"
                )
        print()

        final = {v.relationship_id: v for v in read_relationships(db, version.id)}
        effective = final[first.relationship_id]
        print(
            f"effective decision for {effective.label}: "
            f"{effective.decision} at revision {effective.decision_revision}"
        )
        corrected = final[second.relationship_id]
        print(
            f"effective decision for {corrected.label}: "
            f"{corrected.decision} at revision {corrected.decision_revision}"
            f", pointing at entity {corrected.corrected_entity_id}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
