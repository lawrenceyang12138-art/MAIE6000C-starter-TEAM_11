# C search integration handoff

For the 2026-10-30 PPLX replacement, use the
[team PDF evaluation and recovery guide](search-team-pdf-evaluation.md). It records
the D/B corpus mismatch, immutable-answer mapping to scanned UUIDs, actual PDF
evidence, the C candidate 4/5 semantic gate, and A-owned embedding-job recovery
limitations. Historical results and integration observations below retain their
original dates.

The active model is `perplexity-ai/pplx-embed-v2-late-0.6b` at revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`. Each input produces multiple
128-dimensional token vectors; search uses query-length-normalized MaxSim.
There is no dense pooling and no E5 fallback. The 2026-10-29 E5 PDF results and
older manual-chunk results remain historical evidence, with their original bytes
and hashes. New model evidence belongs in `evidence/C/20261030-pplx/`.

Updated: 2026-10-18. Source branch: `feat/c-search-model-evaluation`.

C now uses B's canonical file, version, and chunk models with a separate search
sidecar. The reverted `develop` history was merged into C, and search and parsing
fixes were restored as separate commits. The validated C result has been merged
back into `develop`, preserving the individual commits. This integration does
not establish completion of A's scan dispatcher, D's UI, or the team's final
acceptance.

Read the [implementation guide](search-plan.md),
[schema adaptation record](search-contract-differences.md), and
[shared integration contract](team11-w7-shared-contract.md) before changing a
shared field or public interface.

## A: schema, authorization, and jobs

The canonical tables are `authorized_roots`, `files`, `file_versions`, and
`source_chunks`. C adds `chunk_search_index`, keyed by the existing source chunk
ID. The actual search migration is `20261015_0002`, following `445f908b73b4`.
It creates search-derived storage and its indexes; it does not create another
file/version/chunk catalog. See the adaptation record for the revision label
proposed in the shared contract and the executable chain in this branch.

The PPLX model uses C's separate `ChunkTokenIndex` sidecar. It stores token
matrices, model ID/revision, token dimensions/count and source-text fingerprint.
The original shared `vector(384)` column is preserved and unused by the active
model. `search_tools migrate` runs shared migrations before calling
`prepare_search_schema`; `search_tools prepare-token-index` adds only C's derived
table to an existing canonical database. A owns rollout and any shared migration
integration. Existing E5 dense vectors require re-indexing with PPLX and cannot
be used as compatible semantic evidence.

`embed_version(db, version_id, backend)` creates keyword sidecars before calling
the embedding backend. It returns `version_id`, `chunk_count`, `embedded_count`,
and `embedding_error`; it does not commit. Every vector batch must succeed before
new vectors are published. Existing vectors and source text remain available on
embedding failure. The caller owns commit/rollback, retry policy, and job status.

Do not use starter case IDs as file-version job targets. A must connect indexing
to the canonical file-job dispatcher after B has committed parsed text. The
standalone indexing command remains useful for an explicit version:

```cmd
python -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id VERSION_ID --backend http --ai-url http://127.0.0.1:8100
```

Search joins authorized roots and accepts `active` or `paused` roots, present
files, and only each file's current `basic_ready` or `enriched` version. Scan
transactions own `current_version_id`. Old chunks must not be substituted for a
new version that has not been parsed. Revoking or revoked roots are excluded.
Server-side mount/path authorization and evidence checks remain required when
opening a source file; request filters do not replace those checks.

Keep the read-only corpus mount, the configured PostgreSQL host port, the
pgvector database image, and the read-only model mount when assembling Compose.

## B: text, pages, and evidence identity

Production input uses canonical `SourceChunk.version_id`, one-based contiguous
`ordinal`, source `text`, and nullable one-based `page_number`. Retain chunk IDs
when text and page identity are unchanged. Search results, relation evidence,
and source evidence must all resolve to that same `source_chunks.id`.

Source chunks do not span pages under the shared contract. Unknown pages remain
unknown. Keep chunks within the embedding size limit where possible; indexing
embeds only the first 2000 characters of a longer passage. Search normalization
belongs in `chunk_search_index`, without rewriting stored source text.

`index_document()` imports synthetic fixture chunks through the canonical models.
It accepts legacy fixture ordering/page fields at its boundary, handles unchanged
content idempotently, and rejects changed text for an existing immutable version.
It does not scan folders or extract PDFs. B's production parser can persist
canonical chunks directly; the dispatcher must then create their keyword indexes
and arrange embedding work. SQL bulk paths must generate normalized search fields
explicitly when bypassing ORM processing.

## D: public search API

```http
POST /search
Content-Type: application/json
```

```json
{"query":"Database backup", "mode":"hybrid", "top_k":10, "root_id":null, "file_id":null}
```

`mode` accepts `keyword`, `semantic`, or `hybrid`, with hybrid as default. The
response preserves the requested `mode`; `effective_mode` reports what ran.
Display a friendly fallback message when `degraded` is true, using
`degradation_reason`. Valid searches with no matches return HTTP 200 and an empty
`results` array. Blank or overlong queries and out-of-range `top_k` return 422.

| Result fields | Meaning |
| --- | --- |
| `root_id` | Authorized directory identity |
| `file_id/file_name/file_path` | File identity, display name, and relative path |
| `version_id/version_created_at` | Immutable version and its display timestamp |
| `chunk_id/ordinal` | Evidence chunk identity and one-based source order |
| `page` | Nullable one-based source page |
| `text` | Source excerpt, at most 2000 characters |
| `score/keyword_score/semantic_score` | Scores between 0 and 1; not probabilities |
| `reason` | Token, filename, and/or token-MaxSim explanation |

Open source evidence through `GET /evidence/{chunk_id}`. Pass the returned chunk
ID through the authorized API and handle missing, superseded, and revoked
evidence distinctly. `total` counts deduplicated files in a bounded candidate
pool; the API returns at most `top_k` files and does not implement pagination.

The historical frontend snapshot `Role_D` at `eb656ca` defaulted to the real API
but still lacked `POST /search` in its adapter. That observation is dated
2026-10-16; recheck D's current implementation before claiming frontend
integration. Browser filtering of already loaded records is not backend search.

## Evidence and remaining acceptance

`submissions/week07/evidence/C/` retains machine-readable model manifests,
evaluation reports, vector records, HTTP/offline checks, and test summaries.
`submissions/week07/search-config-final.json` retains its candidate status.
Historical reports keep their original dates, hashes, Git states, and test counts.
Their initial full-suite result was 49 passes, with keyword Top-1 5/5 and semantic
Top-3 4/5 on synthetic data. `sem-2` remains a page-selection failure.

The 2026-10-18 integrated pre-cleanup verification ran 158 tests and checked real
PostgreSQL/pgvector, migrations, live HTTP fallback, and the starter worker path.
Further cleanup verification belongs to its own run and must not be backdated
into those historical records. ASCII fixture serialization is documented in
[fixture-encoding.json](../submissions/week07/evidence/C/fixture-encoding.json),
including exact decoded-value equivalence and Git-byte hashes.

Individual checklists, presentation text, speaking notes, and duplicate validation
summaries are retained locally and excluded from Git. This handoff and the search
guide carry the useful integration context. Team PDF acceptance, scan-to-index
dispatch, frontend evidence opening, service restart checks, and backup-machine
deployment still require team-level verification.

## Development AI use

Codex assisted with reading requirements, designing and implementing the
Python/SQLAlchemy/FastAPI code, writing tests and documentation, and running
SQLite, PostgreSQL/pgvector, local-model, and HTTP checks. This records tool use;
it does not sign a personal declaration or submit a course statement for a member.
C remains responsible for understanding tokenization, PPLX native query/document
prefixes, token masking and MaxSim, vector compatibility, ranking, page-aware
evaluation, and fallback behavior.

The product's local embedding feature is separate from development assistance. The
evaluation corpus is synthetic and contains no private customer files. D must
assemble and verify the final team AI Use Statement against actual member usage
and the course format.

## 2026-10-30 page-navigation handoff

See the [page-navigation operation guide](search-page-navigation.md) for physical
page semantics, metadata identity/failure behavior, mandatory-root backfill and
the existing vector-recovery command. Public fields and PPLX inputs/weights stay
unchanged. Compare `pplx_only` with `pplx_page_navigation_v1` separately in
`submissions/week07/evidence/C/20261030-page-navigation/`; historical pure-model
3/5 and B's pending review remain visible. A must integrate C's new
`version_page_search_metadata` table into shared migrations and service
preparation. The existing `prepare-token-index` command explicitly creates this
table and token storage meanwhile; search performs no implicit schema writes.
