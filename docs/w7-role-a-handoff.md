# W7 Role A handoff: scan, authorization, dispatch, recovery

Date: 2026-10-29
Branch: `Role_A`
Owner: A (backend integration, directory authorization, scanning, dispatch,
recovery)

This note records what A changed in this round, the interfaces B, C and D need
from those changes, and the parts of the pipeline that are wired but not yet
exercised. It complements `docs/team11-w7-shared-contract.md` section 12, which
is the normative description of the new fields and states.

## 1. Scan -> extract -> index: the path as implemented

```text
POST /roots
  -> validate mount allowlist, lexical path, canonical containment, is-a-directory
  -> authorized_roots row + scan_root job (one transaction)

worker claims scan_root
  -> handle_scan_root(db, root_id, job_id)
     one transaction: files / file_versions / files.current_version_id /
                      extract_file jobs, plus presence and presence_reason
  -> job completed

worker claims extract_file
  -> resolve_source_path(db, version_id)      # containment checked again
  -> handle_extract_file(db, version_id, path)  # B: chunks + version status
  -> _extract_outcome: basic_ready -> job completed + embed_file job queued
                       unsupported  -> job completed, no index job
                       failed       -> job failed, error_code = version reason
  -> one commit closes the job and queues the index job together

worker claims embed_file
  -> embed_version(db, version_id, backend)   # C: keyword sidecar, then vectors
  -> job completed; an embedding error degrades search, it does not fail the job
```

Verified end to end in this round (SQLite, real handlers, real filesystem, real
PDF): `tests/integration/test_scan_recovery.py`. Not verified: the same path on
PostgreSQL with the real AI container (see section 6).

## 2. For B (parsing, evidence, relations)

### 2.1 `handle_extract_file` return contract (now load-bearing)

A's worker no longer treats every returned status as "handled". The mapping is:

| Return value | Job |
| --- | --- |
| `basic_ready` / `enriched` | completed, `embed_file` queued |
| `unsupported` | completed, no index job |
| `failed` | **failed**, retryable, `error_code` copied from `file_versions.error_code` |
| anything else | job fails as an internal error |

Requirements that follow:

1. Return `failed` only for conditions that a retry could fix (source missing,
   source changed, store error). Something permanent belongs to `unsupported`.
2. Always set `file_versions.error_code` before returning `failed` or
   `unsupported`; it is copied to `jobs.error_code` and becomes the only reason
   the client sees.
3. Raising is still correct for non-document failures (database outage). The
   worker records `job_failed` and the version must already be terminal, which
   `handle_extract_file` does today.

### 2.2 Relation generation: seam proposed, not wired

Nothing calls `persist_relations` from the worker today, so a parsed version has
chunks and no relations. A will add the call once the entry point is agreed. The
proposal, in the order A would apply it:

```python
# services/parsing/handler.py (B)
def generate_relations(db: Session, version_id: str) -> int:
    """Derive and store relation candidates for an already-persisted version."""
```

- A calls it from `_process_extract_job` after `basic_ready`, before the job's
  commit, so chunks, relations and the job still land together.
- It must be idempotent per version: re-running must not duplicate relations
  (the existing find-or-create on `relationships` already gives this) and must
  not delete reviews.
- It must not raise for a document with no candidates; "no relations" is a valid
  outcome, not a failure.
- It must not introduce a table. `entities`, `relationships`,
  `relationship_evidence` are canonical.
- It must cost nothing for `unsupported` versions, which never reach this call.

Until this exists, A does not call into `relations.py` at all: relation routes
return whatever is stored, which is nothing unless a test or a script persisted
it.

### 2.3 Evidence and presence

- `files.presence_status` / `presence_reason` are written by the scan. Evidence
  for a file that stopped being readable should refuse with `file_missing` for
  both `missing` and `unavailable`, and must not start serving a stale chunk as
  current.
- `GET /files` now includes `presence_reason` (A added the field to B's router,
  additive and nullable). A file that was never read appears with
  `version_id: null`, `status: "discovered"` and a reason; it is not omitted.

## 3. For C (search index and evaluation)

### 3.1 Index dispatch

- `embed_file` is queued by A's worker only after `handle_extract_file` returns
  `basic_ready` or `enriched`, in the same transaction that closes the extract
  job.
- `embed_version(db, version_id, backend)` stays the entry point; A does not
  touch `chunk_search_index` directly.
- A retry of an extract job whose version already holds `basic_ready` does not
  re-parse, so chunk ids - and therefore `chunk_search_index` rows - stay valid.

### 3.2 Running the evaluation

`evaluate_queries(db, gold, settings, backend)` needs a session whose database
already holds canonical `files`, `file_versions`, `source_chunks`,
`chunk_search_index` and `authorized_roots` rows, all in `present` /
`basic_ready` state.

The cheapest way to produce that shape is the pipeline itself:

```bash
export SEARCH_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:15432/maie6000c
python -m alembic upgrade head
# authorize a folder, then let the worker run scan -> extract -> embed
pytest tests/integration/test_scan_recovery.py -q     # SQLite proof of the shape
```

Environment A relies on and C inherits: `EMBEDDING_MODEL_PATH`,
`EMBEDDING_ENABLED`, `AI_SERVICE_URL`. With AI unavailable the pipeline still
completes and keyword indexes are written; `POST /search` degrades with
`degraded=true`.

## 4. For D (frontend)

1. `GET /files` adds `presence_reason` (`null` when readable). Show
   `presence_status` + `presence_reason` instead of inferring anything from a
   missing row: a file that could not be read now always has a row.
2. `GET /jobs/{job_id}` `error_code` is now the handler's reason
   (`file_missing`, `unreadable`, `source_changed`, `processing_failed`,
   `corrupt`, `encrypted`, `no_text_layer`, `unsupported_format`) or
   `job_failed`. `failed` + `file_missing` is the retryable case.
3. Recovery flow to wire: file reported `failed` -> offer retry ->
   `POST /jobs/{job_id}/retry` (202, `pending`) -> poll the job. A rescan alone
   will not re-extract a failed version by design.
4. `POST /roots` can now answer `404 source_unavailable` for a path that is not a
   directory, in addition to `403 path_out_of_scope` for an escape. Both leave
   no root behind, so the picker can simply show the error.

## 5. Start-up

```bash
docker compose up -d --build          # api runs `alembic upgrade head`
curl -s localhost:8000/health/ready
curl -s localhost:8000/mounts
```

Two new migrations in this round, both additive and nullable, so they apply to an
existing database without a backfill:

```text
20261015_0002 -> 20261029_0003   files.presence_reason   (unreadable-file reason)
              -> 20261029_0004   jobs.error_code         (why the last attempt failed)
```

## 6. Open dependencies and known limits

1. **PostgreSQL chain not run here.** The host has no reachable Docker daemon
   and no local PostgreSQL, so `alembic upgrade head` on an empty PostgreSQL
   database and the postgres-marked tests were not executed. Both migrations were
   verified by offline SQL rendering only.
2. **Relation generation is not wired** (section 2.2). Depends on B's
   `generate_relations` entry point.
3. **`enriched` is never set.** No handler moves a version past `basic_ready`;
   C's embedding step records its result on `chunk_search_index` only. Wiring
   this needs a decision (does a successful embed set `enriched`, and does a
   degraded one leave `basic_ready`?).
4. **Unreadable-file detection is per scan, not watched.** A file that becomes
   unreadable between scans keeps its last `present` state until the next scan;
   continuous watching is out of scope for this round.
5. **A junction created between the walk and the read is not re-checked.**
   Containment is enforced at authorization, at extraction (`resolve_source_path`)
   and for every directory the walk enters, but the walk does not re-resolve each
   file path.
6. **No automatic retry policy.** Retry is always an explicit client action;
   there is no backoff, no attempt ceiling, and no `retry_wait` state.
7. **A worker crash mid-job leaves the job `claimed`.** There is no lease or
   heartbeat, so a job claimed by a process that died stays live: the retry
   endpoint refuses it with `409 active_job_exists` and a rescan does not
   re-dispatch it. Recovering that needs a claim timeout, which is a design
   decision for the next round. Failures the handler *records* (the A2 case) are
   fully recoverable; this is the crash case only.
