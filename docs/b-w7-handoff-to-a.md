# B W7 handoff to A

## Integration surface

The existing A seam remains:

```text
handle_extract_file(db, version_id, source_path) -> version status
read_evidence(db, chunk_id) -> Evidence
read_relationships(db, version_id) -> list[RelationshipView]
record_review(db, relationship_id, ...) -> decision_revision
```

`handle_extract_file` now calls `candidate_relations()` and
`persist_relations()` after chunking. A does not need a new Worker job type,
route assembly change, shared model change, or migration. The existing worker
call is the entry point.

## Timing and transactions

1. B commits the version as `extracting` before reading the source.
2. Chunk persistence, relation/evidence persistence, and the final
   `basic_ready` status share one transaction by invoking `persist_chunks(...,
   commit=False)` and `persist_relations(..., commit=False)`.
3. Any relation persistence failure rolls back chunks and relations, records
   `failed/processing_failed`, and re-raises for the Worker. No partial
   `basic_ready` document is published.
4. Document outcomes remain handled results: abnormal files return
   `unsupported`; missing/changed sources return `failed` with their stable code.
5. After B returns `basic_ready`, A's existing Worker transaction completes the
   extract job and queues one idempotent `embed_file` job.

The Worker should continue to call `resolve_source_path(db, version_id)` and
pass the resulting read-only path. API and Worker must use the same
`source_mounts` allowlist.

## HTTP behavior

The existing `parsing_router` is already included by `services/api/app/main.py`.
A does not need route wiring changes.

Evidence, relation reads, and review writes all recheck current version,
`active|paused` authorization, canonical path containment, source readability,
SHA-256 and byte size.

| code | HTTP |
| --- | --- |
| `chunk_not_found`, `file_missing` | 404 |
| `root_revoked`, `path_out_of_scope` | 403 |
| `source_changed`, `version_superseded`, `evidence_missing`, `review_conflict` | 409 |
| `no_current_version` | 503 |

Relations return a nullable `chunk_id`. A valid relation's ID resolves through
the evidence API; a stale/malformed evidence row returns
`evidence_missing=true`, an empty quote and `chunk_id=null`.

Review rows are append-only. Unique `(relationship_id, decision_revision)` is
the concurrency backstop; a competing write becomes `review_conflict` without
deleting prior history.

## Changes A should not duplicate

- No shared table or enum change is required.
- No migration is required.
- No API main-file change is required.
- No Worker job vocabulary or dispatch change is required.
- Keep B's `source_chunks.id` as the only relation evidence chunk identity.

## Limitations

- Relation extraction is deterministic rule matching, not a complete graph.
- OCR, DOCX/TXT parsing, and file organization remain out of scope.
- Evidence reads hash the current source on every request; this is correct for
  freshness but can be expensive for a very large file.
