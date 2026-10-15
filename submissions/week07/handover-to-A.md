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
would look expired. It will not throw an error; it will just look wrong.

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

## 3. Routes to expose

Three handlers are ready. B has not written routes because they are A's.

| Handler | Suggest route | Notes |
| --- | --- | --- |
| `read_evidence(db, chunk_id)` | `GET /evidence/{chunk_id}` | Returns text, page, path and content hash. Raises `SourceUnavailable` with a reason code when stale; those map naturally to `409` (superseded) and `404` (missing) |
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

One gap worth knowing before the route is written: a `corrected` decision
currently records the decision and a reason but **cannot carry the corrected
label or relation type**. The architecture proposal wants corrections to select
or create a distinct entity. Adding a `corrected_entity_id` column is a small
change; it is deliberately not done yet because it is a schema decision.

## 5. What is already verified, so it does not need re-checking

| Thing | Result |
| --- | --- |
| Whole suite | 72 passed, 1 skipped |
| Static analysis | clean |
| Page attribution against an independent PDF library | 12/12 |
| 12 normal, 3 abnormal, 1 unsupported | passing |
| Relation and review end to end | 3 candidates, revisions 1 and 2 |

Evidence for each is indexed in `submissions/week07/evidence-final.md`.

## 6. What B still owes

- A correction payload, pending the schema decision above.
- Re-running the 12/3/1 regression against the official fixture corpus once D
  delivers it; the current run used a rehearsal corpus.

## 7. What B needs from A

1. The `current_version_id` decision, so evidence stops reading as stale.
2. The source path resolution and the read-only mount, so the handler can run.
3. Confirmation of the schema, or the changes to it.

Until the first of those lands, the search path will look broken even though the
parsing and evidence code is working.
