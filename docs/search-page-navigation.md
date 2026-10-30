# PPLX physical-page navigation

Updated: 2026-10-30. This guide describes C's optional page-navigation layer,
its preparation and recovery commands, and the evidence needed to assess it.
Use it with the [team PDF evaluation guide](search-team-pdf-evaluation.md) and
[shared contract](team11-w7-shared-contract.md).

## Scope and baseline

The historical PPLX PDF run at Git
`40879c44f2777db7dafd559cc97f5edc8b3f6714` scored keyword Top-1 **5/5**, semantic
Top-3 **3/5**, and hybrid Top-3 **3/5**. S02 and S04 selected the correct file at
rank 1 but chose page 1 instead of pages 3 and 2. Their MaxSim margins were
`0.0003624558` and `0.0002039671`. The expected pages, stored vectors and source
evidence were valid. Keyword contribution was zero, so changing hybrid weights
would not resolve those page selections. These are historical pure-model
results; they must remain visible after adding navigation.

Navigation interprets an explicit physical-page request and restricts eligible
chunks before selecting each file's best evidence and applying the file candidate
cap. It adds no score bonus and does not identify a file from document ordinals
or evaluation answers. The complete original query still goes to PPLX.

New pure-model and navigation-assisted results belong in
[`submissions/week07/evidence/C/20261030-page-navigation/`](../submissions/week07/evidence/C/20261030-page-navigation/).
Read the raw reports there for actual results; this guide does not declare that
the candidate gate passed. The C semantic target remains **at least 4/5**, and
is **not a team-frozen acceptance threshold**. B's human gold review remains
`pending`. Navigation-assisted success demonstrates location handling, not an
improvement in PPLX's topical semantic ability. Team topical blind evaluation
and a common deployed corpus remain separate dependencies. Older manual-chunk
**5/5** keyword and **4/5** semantic scores also remain historical.

## Page intent and failure behavior

`services/search/page_navigation.py` recognizes explicit Chinese and English
page expressions: first/opening page or leaf, last/final page, middle/central
page, a numbered page, and a single-page document. Numbered pages support Arabic,
full-width Arabic and supported Chinese numerals. A page/leaf context is required.
For example, `第十份资料的第二页` requests page 2; it does not bind the tenth
document to a filename. `第三章`, `中间件` and `最后更新` alone are ordinary queries.
Negation, conflicting targets, ranges and unsupported numeric forms leave
ordinary ranking in place.

Pages mean one-based physical PDF order, including blank pages. An odd page
count has one central page; an even count permits both central pages and the
existing retrieval score chooses between them. Several chunks on one page remain
separate candidates; the returned text, page, chunk and score all belong to the
same selected chunk. A known out-of-range target, blank target page, unknown
chunk page or single-page request against a multi-page file cannot be satisfied
with a neighboring page. That file contributes no result.

Page metadata is read from the database. Search does not open PDFs, derive counts
from chunks or create tables. If compatible metadata is unavailable, that file
keeps ordinary ranking; existing hit `reason` text reports, for example,
`page navigation not applied: page_metadata_missing` or
`page navigation not applied: page_metadata_stale`. A missing sidecar schema is
`page_metadata_schema_missing`. Evaluation diagnostics additionally record
`page_count`, `metadata_status`, `target_pages`, `applied`, eligible/target chunk
counts, selected chunk/page and the decision reason. Empty results have no hit
`reason`; consult these internal diagnostics for `page_out_of_range`,
`single_page_required` or `target_page_without_text_chunk`.

The public search request and response fields are unchanged. The internal
setting `SEARCH_PAGE_NAVIGATION_ENABLED` defaults to `true`; CLI evaluation uses
`--page-navigation` or `--no-page-navigation`. Reports label the profiles
`pplx_page_navigation_v1` and `pplx_only` respectively. Runtime code never reads
query IDs, gold answers or fixture manifests.

Keyword mode keeps its existing ranking. Full AI fallback also keeps ordinary
keyword behavior and disables navigation. The response retains requested `mode`,
reports `effective_mode=keyword`, `degraded=true`, and an explicit
`degradation_reason` such as `ai_disabled`, `ai_unavailable`, `ai_timeout` or
`embeddings_not_ready`. Keyword evidence stays readable. Partial vector coverage
retains the requested semantic/hybrid mode with `partial_embeddings` and
`degraded=true`; navigation cannot clear that state. Every degraded semantic or
hybrid execution remains a failed semantic evaluation row.

Current-version, readable-root, present-file and request-scope filtering applies
before navigation. Active and paused roots are readable; revoked roots and old
versions remain excluded. Results retain one hit per file. Equal names at
different paths do not become the same file. Opening evidence still requires the
existing authorized path and source-identity checks.

## Derived metadata and explicit preparation

C's additive table `version_page_search_metadata` references the canonical
`file_versions.id`. It contains `version_id`, `content_sha256`, `byte_size`,
nullable `parser_revision`, `page_count`, `policy_revision`, `created_at` and
`updated_at`. The policy is `pdf-physical-pages-v1`. Search requires exact
version/content/size/parser/policy compatibility and a positive page count.

`prepare_version_page_metadata` resolves the current authorized source, verifies
its SHA-256 and size before and after opening the PDF, and reads its actual
physical page count. Counts come from PDF structure, including blank pages,
never gold or the largest chunk page. Encryption, corruption, changed bytes,
unavailable mounts and unsupported files have separate safe error codes.

Run from this worktree with the prepared Python environment. On a fresh
PostgreSQL/pgvector database, the Alembic command creates the shared schema and
both C sidecars through `20261030_0005`:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools migrate --database-url YOUR_DATABASE_URL
```

For an older canonical database whose head predates `20261030_0005`, the
idempotent preparation command remains a compatibility path. Its historical
name is retained; it creates both C token storage and page metadata with
`checkfirst=True`:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools prepare-token-index --database-url YOUR_DATABASE_URL
```

These commands do not populate page counts or vectors. Search does not perform
implicit DDL. A PostgreSQL integration test upgrades a disposable database from
empty to the single Alembic head and verifies both sidecars.

## Backfill page counts without re-embedding

Use the existing server allowlist and the same source mounts as API/Worker.
`SOURCE_MOUNTS` is a JSON map from the database root's actual `mount_id` to the
read-only source directory; it is not a client-provided absolute path. For a
standalone Windows command, configure that map in the process environment or
the project's existing configuration. Do not substitute an unrelated directory.

`page-metadata` **requires `--root-id`**. An omitted root is rejected; there is
no implicit global backfill. It selects only present files' current
`basic_ready`/`enriched` versions under an active/paused root. Optionally narrow
to one current version within that root:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools page-metadata --database-url YOUR_DATABASE_URL --root-id AUTHORIZED_ROOT_UUID --output work/page-metadata-root.json
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools page-metadata --database-url YOUR_DATABASE_URL --root-id AUTHORIZED_ROOT_UUID --version-id CURRENT_VERSION_UUID --output work/page-metadata-version.json
```

The JSON records selected/ready/error version counts and each version's actual
page count or error. A specified old version, another root's version, missing
file or unready version is refused as outside the selected scope. Per-version
metadata failures are recorded and produce a failing command result. Resolve
the mount/source/parser issue and repeat the same scoped command. A root with
zero selected versions is reported with an explicit zero denominator.

The normal `index` command also attempts page metadata preparation. Its
`IndexResult` now includes `page_count` and `page_metadata_error`, separately
from `embedding_error`. A metadata failure does not block keyword sidecars,
vector publication or original evidence. Conversely, successful vectors do not
prove that page metadata is ready. Inspect both fields.

## Local model and vector recovery

Model preparation remains the explicit network step. Inference uses verified
local files or the internal AI service and has no cloud fallback:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools download-model --model-path models/pplx-embed-v2-late-0.6b
```

The [existing preparation/recovery guide](search-team-pdf-evaluation.md) covers
Python dependencies and pinned artifact verification. Navigation changes no
model input, tokenizer, prefix, chunking, vector or retrieval weight. Existing
compatible PPLX vectors need no rebuild just to enable navigation; the scoped
`page-metadata` command supplies the new sidecar independently.

| Parameter | Frozen value |
| --- | --- |
| Model | `perplexity-ai/pplx-embed-v2-late-0.6b` |
| Revision | `7bba8e7cf2075dec747fa8557f41eb90e70361ed` |
| Representation / scoring | 128 dimensions per token; normalized token MaxSim mean |
| Native query / document prefixes | `[Q] ` / `[D] ` |
| Chunk input / model token limits | first 2,000 characters; query 1,024 / document 4,096 tokens |
| Parser chunk / overlap / minimum | 700 / 120 / 80 characters |
| Request batch / model forward batch | at most 16 / 4 inputs |
| Runtime | CPU float32, 4 threads; verified local files |
| Query limits | 500 characters, 64 distinct searchable tokens |
| Keyword / semantic weights | 0.65 / 0.35, normalized by their sum |
| Candidate cap | 200 files after each file's eligible best chunk |
| Evaluation Top-k | 3 recorded; keyword scored at Top-1 |
| Public Top-k | default 10, maximum 50 |
| HTTP AI timeout | 10 seconds; direct local inference has no HTTP deadline |

After AI is restored, warm the local service once and run the existing indexing
command for each current readable version with missing/incompatible vectors:

```powershell
$navigationWarmup = @{ texts = @("warm up"); kind = "query" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8100/embeddings -Method Post -ContentType application/json -Body $navigationWarmup -TimeoutSec 120
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id CURRENT_VERSION_UUID --backend http --ai-url http://127.0.0.1:8100 --timeout 10
```

For an offline in-process recovery use `--backend local --model-path
models/pplx-embed-v2-late-0.6b`. Check `embedding_error=null`,
`embedded_count=chunk_count`, and the separate metadata outcome; then rerun
semantic/hybrid search and read each returned chunk's evidence. Source and chunk
IDs need not change. No dedicated recovery API/UI is introduced. A still owns
Worker job-state/retry handling; a completed job alone does not establish
compatible vector completeness.

## Compare pure model with navigation

Use the same exact manifest corpus, frozen gold, model, database and parameters
for the two profiles, with separate output files. The full PDF runner performs
normal scan, parse and indexing and verifies source bytes. Point it only at a
dedicated evaluation database. These commands are reproduction instructions,
not claims that a run has already passed:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url YOUR_DATABASE_URL --backend local --model-path models/pplx-embed-v2-late-0.6b --stage-dir work/team-pdf-page-navigation-corpus --no-page-navigation --output work/team-pdf-pplx-only.json
.\.venv-pplx\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url YOUR_DATABASE_URL --backend local --model-path models/pplx-embed-v2-late-0.6b --stage-dir work/team-pdf-page-navigation-corpus --page-navigation --output work/team-pdf-pplx-navigation.json
```

For SQLite, use a fresh URL such as
`sqlite:///work/team-pdf-page-navigation.db`; repeat with an A-provisioned
disposable PostgreSQL/pgvector database to validate its real migration/SQL path.
To evaluate an existing parsed/indexed database without another ingestion, use
the `search_tools evaluate` adapter with its actual root UUID:

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools evaluate --database-url YOUR_DATABASE_URL --gold submissions/week07/gold-queries.json --manifest fixtures/manifest.json --freeze submissions/week07/gold-queries.freeze.json --root-id AUTHORIZED_ROOT_UUID --backend local --no-page-navigation --output work/existing-pplx-only.json
.\.venv-pplx\Scripts\python.exe -m scripts.search_tools evaluate --database-url YOUR_DATABASE_URL --gold submissions/week07/gold-queries.json --manifest fixtures/manifest.json --freeze submissions/week07/gold-queries.freeze.json --root-id AUTHORIZED_ROOT_UUID --backend local --page-navigation --output work/existing-pplx-navigation.json
```

That adapter does not replace the full runner's on-disk corpus checks. Five
keyword queries execute once and five `semantic_description` queries each execute
semantic and hybrid retrieval: **10 frozen queries, 15 searches, separate
denominators of 5/5/5**. Every mode records complete Top-3 results, requested and
effective modes, degradation, actual ranks/pages/chunks and navigation decisions.
Each hit must agree with canonical evidence; the full runner also checks the
authorized source hash. Reports retain corpus/answer hashes, parser/model
versions, Git state, exact command, duplicate-file counts and pending B review.
A failed quality gate saves the report and exits 1. Do not change the freeze or
count degraded fallback as a model success.

## Independent navigation regression

`fixtures/search/page-navigation-v1.json` was frozen before implementation at
`77a9af1`; its freeze record is in
`fixtures/search/page-navigation-v1.freeze.json`. The fixture SHA-256 is
`cc49c7bdcf74337a32350dfbc9548ae63c39c118cdf7968f85869a1610f99bab`.
It contains **24 explicit navigation and 12 ambiguous/unavailable cases**,
covering Chinese/English, unrelated filenames, 1/2/3/4/7/10 physical pages, both
even central pages, blank targets/tails, multiple chunks on one page, unknown
pages, metadata absence/staleness and out-of-range targets. Freeze changes
require a separately versioned specification, not edits after seeing results.

The verifier generates its own real PDF corpus and uses production
scan/parse/index handlers. Its scoring backend is deliberately deterministic
hand-constructed token vectors favoring earlier pages; **it does not run PPLX**.
This separates navigation correctness from model quality. Missing/stale metadata
and unknown chunk pages are explicit test-only faults applied after ingestion.
All 36 cases run semantic and hybrid with and without navigation: **72 enhanced
and 72 baseline executions**. Reports check both page behavior and diagnostic,
source-hash, version/chunk/page/original-text consistency.

```powershell
.\.venv-pplx\Scripts\python.exe -m scripts.verify_page_navigation --database-url sqlite:///work/navigation-regression.db --work-dir work/navigation-regression-pdfs --output work/navigation-regression-sqlite.json
.\.venv-pplx\Scripts\python.exe -m scripts.verify_page_navigation --database-url YOUR_SEPARATE_POSTGRES_REGRESSION_DATABASE_URL --work-dir work/navigation-regression-pg-pdfs --output work/navigation-regression-postgres.json
.\.venv-pplx\Scripts\python.exe -m pytest tests/unit/test_search_page_navigation.py tests/unit/test_search_page_metadata.py tests/integration/test_page_navigation_regression.py -q
```

Use a separate database from the team PDF evaluation. The regression runner
refuses another root's database or an unowned nonempty corpus directory. Repeat
runs verify exact source bytes and preserve IDs. The behavioral regression does
not replace real PPLX evaluation, HTTP disconnect/timeout/backfill recovery,
source-scope tests or the wider PostgreSQL test suite. Actual dated commands,
passes/skips and limitations belong to the new evidence directory.

## Handoff and remaining dependencies

- **A:** integrate `version_page_search_metadata` and token storage into the
  shared migration/deployment path; retain explicit preparation before search.
  Provision PostgreSQL/pgvector, verified local model files and identical
  API/Worker source allowlists. Connect parsed-version indexing and inspect
  `page_metadata_error` separately from embedding readiness. Resolve Worker
  completion/retry semantics and verify restart/backup deployment.
- **B:** complete the pending manual review of expected text, source and physical
  pages; confirm unknown/blank-page handling. Parser revision changes make
  metadata stale until it is explicitly regenerated against current source bytes.
  Retain canonical version/chunk identities and original evidence.
- **D + B:** agree on one path/hash/page-count corpus. Current D gold and B's
  deployed fixtures differ. Preserve existing answers; publish a newly frozen,
  human-reviewed topical benchmark for semantic quality and decide the team
  threshold separately. Navigation scores must carry their assisted profile.
- **D + A:** consume existing search/evidence fields and expose existing
  degradation faithfully. Public schema, API assembly, Worker integration and
  frontend changes are outside C's navigation implementation. A dedicated
  recovery API/UI is not required for this round.
