# Search schema adaptation and historical contract differences

Updated: 2026-10-18. This handoff describes the canonical models currently used by
`feat/c-search-model-evaluation`. The differences originally recorded on
2026-10-16 explain the adaptation; they are not a claim that the old duplicate
schema is still in use. See the [implementation guide](search-plan.md),
[integration handoff](search-integration-handoff.md), and
[shared integration contract](team11-w7-shared-contract.md).

## Historical comparison

The original review compared standalone C with these remote snapshots:

- B: `w7-parsing`, `c248e8a9272f76beeec8f50a50bfd727f035aed9`.
- A: `w7-scan-dispatch`, `7b084e573edd4e4c6985685ce8a3c7189aa3504c`.

Standalone C and B both created `source_chunks` after the starter migration, with
different columns. Combining those migration files unchanged would have produced
multiple heads and duplicate table creation. B's relation evidence also referred
to existing chunk IDs, so copying passages into a parallel C schema would have
broken the evidence relationship.

## Canonical mapping implemented in C

| Meaning | Former standalone C representation | Current canonical representation |
| --- | --- | --- |
| File identity | `SourceFile` / `source_files` | `FileRecord` / `files` |
| Authorized directory | Not joined | `AuthorizedRoot` / `authorized_roots` |
| Current version | `SourceVersion.is_current` | `FileRecord.current_version_id` |
| Content hash | `SourceVersion.sha256` | `FileVersion.content_sha256` |
| Display version | `version_number` | Stable `version_id` and `version_created_at` |
| Searchable state | File and version `ready` | Present file; version `basic_ready` or `enriched` |
| Chunk version key | `source_version_id` | `version_id` |
| Chunk order | Zero-based `chunk_index` | One-based `ordinal` |
| Source page | `page_start/page_end` | Nullable `page_number`; API field `page` |
| Keyword data | Columns on C's `SourceChunk` | `ChunkSearchIndex.search_text/search_terms` |
| Vector data | Columns on C's `SourceChunk` | `ChunkSearchIndex.embedding`, model, and dimensions |
| Evidence identity | Separate search records | Existing `source_chunks.id` throughout |

Retrieval now joins `SourceChunk`, `ChunkSearchIndex`, `FileVersion`, `FileRecord`,
and `AuthorizedRoot`. It accepts roots in `active` or `paused`, files marked
`present`, and only the version referenced by `current_version_id`. Versions must
be `basic_ready` or `enriched`. `root_id` and `file_id` request filters narrow that
scope. A pending new version must not cause an older version to be presented as
current content.

The canonical schema has no version sequence number. The import adapter still
accepts legacy fixture fields at its boundary; production responses use the
canonical fields above. Unknown source pages remain unknown. Search does not
invent page numbers or require B to change its source chunk IDs.

## Migration chain in this branch

```text
20260713_0001
  -> c2d1ac693a0e
  -> 318ab5be35e0
  -> 445f908b73b4
  -> 20261015_0002
```

The adapted `20261015_0002_source_search.py` follows `445f908b73b4`. It adds the
search sidecar, the PostgreSQL vector extension, and its GIN index without
recreating file, version, or source chunk tables. The shared contract proposed
the label `20261017_0003`; the actual migration in this branch retains
`20261015_0002`. Inspect the migration files and `alembic heads` for the executable
revision. Coordinate any revision renaming with the owner of deployed databases.

Use a disposable empty database to validate this canonical chain. Databases that
ran the former standalone schema contain historical test data and need an
explicit migration or replacement plan; combining old tables by hand is not an
upgrade procedure.

## Transaction and indexing boundary

`embed_version(db, version_id, backend)` reads canonical chunks and creates their
keyword sidecars before attempting embeddings. It publishes vectors only after
every batch succeeds and returns `IndexResult`; it does not commit. Existing
vectors and source text survive an embedding failure. The caller owns the
transaction and job outcome.

When parsing replaces a chunk, the sidecar associated with the old chunk can be
removed through its cascading foreign key. A must arrange keyword indexing and
embedding work for replacement chunks. SQL bulk writes must populate the same
normalized keyword fields as the ORM path.

## Work still owned by the team

A's reviewed decisions assign the current-version pointer to the scan
transaction, use server-approved read-only mounts, and dispatch extraction only
for newly observed content. The C branch's schema adaptation does not establish
that A's full scan and file-job dispatcher or D's frontend is integrated.

Keep A's source mount and host-port policy when combining Compose changes, along
with C's `pgvector/pgvector:pg16` database and read-only model mount. Shared models,
schemas, migration assembly, configuration, and public route assembly remain
subject to A's review; D owns final frontend assembly.

Team acceptance must exercise authorization and revocation, current-version
publication, extraction followed by indexing, keyword fallback, consistent
search/evidence IDs, database upgrades, and service restart behavior. Independent
module tests and historical branch snapshots are evidence for their stated scope.
