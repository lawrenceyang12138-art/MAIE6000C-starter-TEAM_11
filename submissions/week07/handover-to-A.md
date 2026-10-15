# Handover from B to A

Owner: B (read files). Reader: A (files, infrastructure, shared schema, routes).

B's module is finished and verified, but **nothing is wired in yet**. This note
says exactly what integration needs, in the order it should happen. Each item
states the boundary question as a decision rather than a task, because A owns
that answer.

---

## 1. Decision needed: who sets `file.current_version_id`?

**This is the one that will silently break the demo if it is missed.**

The evidence read path decides whether a passage is still current by comparing
its version against `files.current_version_id`. Nothing in B's code sets that
column, and it is not set anywhere else either.

**Consequence today:** every passage reads as stale, so every search result
would look expired. It will not throw an error; it will just look wrong. As of
2026-10-15 it also says which of the two situations it is: the refusal code is
`no_current_version`, not `version_superseded`, because "nobody has marked a
current version" and "this passage is historical" have different fixes.

Two options:

- **Scan sets it** (B's preference). "Current version" means the newest content
  observed on disk, which is what a scan has just determined. B's extraction
  handler processes a version that scanning already decided exists.
- **Extraction sets it**, once a version reaches `basic_ready`. Simpler to
  implement, but it means a version is only "current" after its text is ready,
  so a freshly scanned file has no current version at all until parsing
  finishes.

Either is defensible; they differ in what the interface shows during the window
between scanning and parsing. B's code works with either and does not need
changing.

## 2. Wiring the handler into the worker

B provides one entry point:

```
handle_extract_file(db, version_id, source_path) -> resulting status
```

It never raises for a document problem, so the dispatch loop can call it in a
`try` and move on. The intended call shape is the one used in
`tests/integration/test_extraction_regression.py`.

Two things A needs to supply:

- **The source path.** The handler needs a resolved filesystem path for the
  version. Resolving it from the mount allowlist is A's boundary, not B's.
- **A `SOURCE_MOUNT_ROOT` setting and a read-only mount** in `compose.yaml` for
  the api and worker services. Neither exists yet.

After the call, marking the job completed or failed is A's transaction. The
handler only records the outcome on the file version.

The change to A's dispatch loop is small, so here it is as a proposal rather
than as an edit - `services/worker/app/main.py` is A's file and B has not
touched it:

```
# services/worker/app/main.py
from services.common.models import RootJobType
from services.parsing import handle_extract_file

HANDLED_JOB_TYPES = {
    JobType.TRIAGE_CASE.value,
    RootJobType.EXTRACT_FILE.value,   # otherwise the job stays pending forever
}

def process_job(job_id: int) -> None:
    ...
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        # This branch has to come before the case lookup: an extract_file job
        # has no case_id, and the existing code raises "Case not found" for it.
        if job.job_type == RootJobType.EXTRACT_FILE.value:
            source_path = resolve_source_path(db, job.version_id)  # A's resolver
            handle_extract_file(db, job.version_id, source_path)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = utcnow()
            db.commit()
            return

        case = db.get(Case, job.case_id)
        ...
```

Without the branch, an `extract_file` job does not fail quietly: the existing
code raises `Case not found for job N`, the job is marked failed, and the
error looks like a data problem rather than a missing dispatch case. That is
worth knowing before someone spends an afternoon on it.

**Rebuild the image, do not just restart it.** The api container runs
`alembic upgrade head` on start, and the image carries its own copy of
`alembic/`. After pulling these migrations, a plain `docker compose up -d`
starts a container whose alembic does not know revision `445f908b73b4` while
the database is already at it, and the container exits with:

```
FAILED: Can't locate revision identified by '445f908b73b4'
```

The fix is one flag:

```
docker compose up -d --build
```

This was hit and confirmed on 2026-10-15, not predicted. Anyone who pulls this
branch - A, C, D, or the second laptop - will hit it otherwise.

## 3. Routes to expose

Three handlers are ready. B has not written routes because they are A's.

| Handler | Suggest route | Notes |
| --- | --- | --- |
| `read_evidence(db, chunk_id)` | `GET /evidence/{chunk_id}` | Returns text, page, path and content hash. Raises `SourceUnavailable` with a reason code: `version_superseded` maps to `409`, `chunk_not_found` and `file_missing` to `404`, `root_revoked` to `403`, and `no_current_version` to `503` - that last one is not the caller's fault, it means the pipeline has not marked anything current yet |
| `read_relationships(db, version_id)` | `GET /versions/{version_id}/relations` | Already bounded in code, so the route cannot return an unbounded graph |
| `record_review(db, relationship_id, decision, expected_revision, …)` | `POST /relations/{id}/reviews` | `ReviewRefused` with `review_conflict` maps to `409`; `invalid_decision` to `422` |

The reason codes are stable strings, so the route can pass them straight
through to the client rather than inventing a second vocabulary.

## 4. Schema proposal awaiting A's decision

Four tables are already in a working migration:
`entities`, `relationships`, `relationship_evidence`, `reviews`.

They were added as a **proposal**, because the schedule gives A the schema
decision. The migration applies and downgrades cleanly on PostgreSQL. If A
changes a column, B's code needs to follow, so please say what changes rather
than editing silently.

A `corrected` decision now has to name the entity it points to instead. The
`reviews` table carries `corrected_entity_id`, and `record_review` refuses a
correction that names no replacement, a confirmation or rejection that names
one, and a replacement that is not an entity. So the route takes one optional
field, `corrected_entity_id`, and passes it through:

| Decision | `corrected_entity_id` |
| --- | --- |
| `confirmed` | must be absent |
| `rejected` | must be absent |
| `corrected` | **required**, must be an existing `entities.id` |

Three reason codes come back for the route to map:
`correction_without_target` and `correction_target_not_allowed` to `422`,
`corrected_entity_not_found` to `404`. The column was added after the rest of
the tables, so the migration `445f908b73b4` must run with the others.

That closes the last known gap in B's slice. What a correction still cannot
express is a **new** entity that does not exist yet: the correction points at
an entity row, so creating one first is the caller's job. That is a deliberate
boundary rather than an oversight — inventing entities from a review is
exactly the kind of silent data creation this system should not do.

## 5. What is already verified, so it does not need re-checking

| Thing | Result |
| --- | --- |
| Whole suite | 87 passed, 2 skipped |
| Static analysis | clean |
| Page attribution against an independent PDF library | 12/12 |
| 12 normal, 3 abnormal, 1 unsupported | passing |
| Relation and review end to end | 3 candidates, revisions 1 and 2, one correction carrying its replacement entity |

Evidence for each is indexed in `submissions/week07/evidence-final.md`.

## 6. What B still owes

- Re-running the 12/3/1 regression against the official fixture corpus once D
  delivers it; the current run used a rehearsal corpus.

## 7. What B needs from A

1. The `current_version_id` decision, so evidence stops reading as stale.
2. The source path resolution and the read-only mount, so the handler can run.
3. Confirmation of the schema, or the changes to it.

Until the first of those lands, the search path will look broken even though the
parsing and evidence code is working.
