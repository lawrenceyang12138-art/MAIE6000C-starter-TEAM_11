# Handover from B to C: the two halves do not share a data model yet

Owner: B. Reader: C (search, embeddings, evaluation).

Written on 2026-10-17 after checking every branch on the team repository. This
is not a style comment: **the branches do not merge into a working system as
they stand**, and the reason is a schema collision rather than a hard problem.

## What is actually true right now

| Branch | Commits | Own tests |
| --- | --- | --- |
| `w7-parsing` (B) | 68 | **101 passed, 1 skipped** |
| `w7-scan-dispatch` (A) | 4 | 6 passed, 1 skipped |
| `feat/c-search-model-evaluation` (C) | 2 | **46 passed, 3 skipped** (after rebuilding the image) |
| `Role_D` (D) | 4 | 4 passed, 1 skipped |

Each branch is healthy on its own. Merging them is the problem:

- A's branch merges into B's with **no conflicts**
- D's branch merges into B's with **no conflicts**
- C's branch conflicts with B's in three files: `services/common/models.py`,
  `services/common/schemas.py`, `services/api/app/main.py`

The first two conflicts are additive (two import lists, two blocks of table
definitions). **The real problem is underneath them.**

## The collision

Both halves invented storage for the same things, with the **same table name**:

| | B (`w7-parsing`) | C (`feat/c-search-model-evaluation`) |
| --- | --- | --- |
| File | `files` | `source_files` |
| Version | `file_versions` | `source_versions` |
| Chunk | **`source_chunks`** | **`source_chunks`** |

Two SQLAlchemy classes cannot both own `source_chunks`, and both migrations
declare the same parent:

```
B: c2d1ac693a0e (down_revision 20260713_0001) -> 318ab5be35e0 -> 445f908b73b4
C: 20261015_0002 (down_revision 20260713_0001)
```

After a merge, Alembic has **two heads** and `alembic upgrade head` refuses to
run. That failure is a good outcome - the alternative would be one model
silently winning at runtime while the other's tables sit empty.

## What each side actually needs

B's model exists to answer "which text came from which bytes, on which page",
and it is already migrated, tested and measured (101 tests, 12/12 page
attribution, 66 pages with no dropped glyphs).

C's model exists to answer "which passage is closest in meaning to this query",
and the only thing it stores that B does not is **the embedding itself** (plus
the derived `search_text` and `search_terms`).

So the split of responsibilities is already clear:

**B keeps the files, versions and chunks. C keeps the vectors.**

## The field mapping, exactly

| C's field | B's field | Note |
| --- | --- | --- |
| `source_files.id` | `files.id` | |
| `source_files.path` | `files.relative_path` | B stores paths relative to an authorised root |
| `source_files.name` | `files.name` | |
| `source_files.sha256` | `file_versions.content_sha256` | B puts the hash on the **version**, because the same file has several versions |
| `source_files.status` | `files.presence_status` + `files.current_version_id` | "current" is a pointer on the file, not a flag on the version |
| `source_versions.source_file_id` | `file_versions.file_id` | |
| `source_versions.sha256` | `file_versions.content_sha256` | |
| `source_versions.version_number` | - | B identifies a version by its content hash; order by `created_at` |
| `source_versions.is_current` | `files.current_version_id == version.id` | same question, different place for the answer |
| `source_versions.status == "ready"` | `file_versions.status == "basic_ready"` | B's vocabulary; `unsupported` and `failed` are separate outcomes |
| `source_versions.page_count` | - | B does not store it; the chunk pages are the citation |
| `source_chunks.source_version_id` | `source_chunks.version_id` | |
| `source_chunks.chunk_index` | `source_chunks.ordinal` | |
| `source_chunks.page_start` / `page_end` | `source_chunks.page_number` | B's chunks **never cross a page**, so start == end by construction |
| `source_chunks.text` | `source_chunks.text` | identical |
| `source_chunks.search_text`, `search_terms` | derived from `text` | B already normalises whitespace, CJK spacing and unreadable glyphs |
| `source_chunks.embedding` | **new** | the one thing C adds |

## What this means in practice

1. **Keep B's file/version/chunk tables.** They are the ones with migrations,
   tests and measured page attribution behind them; B's slice also stops a
   re-process from orphaning evidence by keeping unchanged chunk rows, which is
   exactly the stability an embedding table needs.
2. **Add C's embedding storage to B's chunk.** Either a nullable `embedding`
   column on `source_chunks` (plus `embedding_model`, `embedding_dimensions`),
   or a separate `chunk_embeddings` table keyed by `source_chunks.id` with
   `ON DELETE CASCADE`. A separate table keeps the parsing table free of a
   model-specific type and lets an embedding be regenerated without touching
   the text.
3. **Re-parent C's migration after B's head** (`445f908b73b4`) instead of
   branching from the initial revision, or add an explicit `alembic merge`
   revision. Then there is one head again.
4. **Adapt two files in `services/search/`**: `indexing.py` writes chunks, and
   `retrieval.py` joins them. Both queries need B's field names and B's status
   vocabulary; the rest of C's module (tokenising, ranking, evaluation) does
   not touch the schema.
5. **Rebuild the image after the merge.** C's `pyproject.toml` adds
   `pgvector==0.4.1`; without `docker compose up -d --build` the api container
   dies on import.

## What B can offer

- B's `source_chunks.id` is **stable across a re-process when the text is
  unchanged** (verified by test), so re-indexing is only needed when the text
  actually changes.
- Every chunk carries `page_number` and a verified quote, so a search hit can
  show "page 7" and the sentence without C storing either.
- B's `read_evidence` already refuses passages whose version is no longer
  current; C's retrieval can call it instead of re-implementing the staleness
  rule - the same four refusals, one implementation.

Both halves are good work. They were built in parallel and did not share a
schema, and the fix is a mapping plus one migration, not a rewrite.
