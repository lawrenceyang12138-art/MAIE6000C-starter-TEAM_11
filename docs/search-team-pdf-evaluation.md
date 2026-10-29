# Team PDF search evaluation and recovery

Prepared by C on 2026-10-29; model replacement updated 2026-10-30.
Work branch: `codex/c-team-pdf-evaluation`.
Integration baseline: `7522287126061da8977c253256e8f807143ab8b5`.
The HTTPS fetch observed remote develop at
`047b2ac8b6c584b366c3db8f211125a6b9febe4f`, already included in that local baseline.
The original C checkout and its untracked frontend/tmp files remain untouched.

The active model is now `perplexity-ai/pplx-embed-v2-late-0.6b` at fixed revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`. This is ColBERT late interaction:
each input retains a matrix of 128-dimensional token vectors and search computes
MaxSim. It is not a late-chunking model and is not pooled into a single dense
vector. The previous E5 weights are retired. Their dated reports in
`submissions/week07/evidence/C/team-pdf-20261029/` and the older manual-chunk
reports remain unchanged. Record new results separately in
`submissions/week07/evidence/C/20261030-pplx/`; never infer a new score from an
old model's report.

## Answers, identity, and score interpretation

The inputs are D's `submissions/week07/gold-queries.json`, its adjacent freeze
record, and `fixtures/manifest.json`. Their immutable identities are:

| Input | Version | SHA-256 |
| --- | --- | --- |
| Gold | `team11-gold-v1` | `d1d7b7daf285ed8ad596546dc1cacb28bca7b23cd26edc748e7636e1a23db053` |
| Corpus manifest | `d-fixtures-v1` | `3ad53b3f8ccdc7ac6b84457fcedf9a735fe0ddf7ceb8004eb97b46ab17e3280f` |
| Freeze | `team11-gold-freeze-v1` | Recorded in each raw evaluation |

The 16 files contain 12 normal PDFs with 20 pages, three abnormal PDFs and one
unsupported document. D labels this a **source-location smoke test, not a
semantic-quality benchmark**. B's human review remains `pending`. C's candidate
gate is keyword Top-1 **5/5**, requiring both file and page, and semantic Top-3
**at least 4/5**. The semantic gate has **not been frozen by the team**. Hybrid
Top-3 is reported separately with no invented team gate. These distinctions also
appear in every raw report.

`evaluation_sources.py` maps each expected alias through its manifest entry to
an authorized root UUID, an exact relative path and the current content SHA-256.
The resulting file/version IDs come from scanning. A matching filename, a copy
in another root, or a matching historical version cannot substitute for the
expected source. `expected[]` represents acceptable locations: any matching
file/version/page is a hit, and every alternative is diagnosed. Invalid entries
remain in the denominator. Missing/invalid root scope prevents execution rather
than issuing a global search.

For an already scanned database, `scripts.search_tools evaluate --gold ...
--manifest ... --freeze ... --root-id UUID` uses the same adapter. Its freeze
check also runs before database access or inference. Its ranking settings inherit
the process's `SEARCH_*` environment variables and are recorded under
`parameters`; the full PDF runner exposes those values as explicit CLI options.

Five keyword queries execute once; five `semantic_description` queries each
execute semantic and hybrid search. Thus there are **10 frozen queries, 15
searches, and separate denominators of 5/5/5**. All modes record Top-3, while
keyword scoring uses only rank 1. Every returned chunk is read through B's
evidence handler and checked for version/page/original-text agreement; the PDF
runner additionally checks the authorized on-disk source hash. A degraded
semantic or hybrid row never counts as a model hit, even if its keyword fallback
finds a correct location.

The older hand-authored chunk benchmark's keyword **5/5** and semantic **4/5**
remain historical results. `fixtures/search/` and the existing historical C
reports/configuration have not been rewritten as team PDF evidence.

## Reproduce the PDF pipeline

Use Python 3.11 and a fresh local environment. Run commands from this C worktree:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,embeddings]" --timeout 120
.\.venv\Scripts\python.exe -m scripts.search_tools download-model
.\.venv\Scripts\python.exe -m scripts.validate_d_gold
```

Model preparation is the explicit network step. All fixed-revision files in
`MODEL_FILES`, including nested Sentence Transformers modules, must
match `PINNED_MODEL_SHA256` before a local manifest can be written. Offline
loading checks those same fixed hashes, the manifest's model/revision, and vector
dimensions. Native inference uses Sentence Transformers 6 or later and
Transformers 5.4 or later; each raw run records the exact installed versions.
Arbitrary replacement files cannot authenticate themselves by
rewriting the manifest. Weights stay in ignored `models/`; copy those verified
files and their manifest when preparing another computer. The active path is
`models/pplx-embed-v2-late-0.6b/`. Runtime does not download missing weights or
fall back to E5 or a hosted model.

Create an isolated PostgreSQL/pgvector instance, or supply a disposable database
URL. Do not point the runner at a shared production database. The historical
2026-10-29 E5 run used:

```powershell
docker run --detach --name team11-c-pdf-eval-20261029 --label owner=codex-role-c --publish 127.0.0.1:55432:5432 --env POSTGRES_DB=team11_c_pdf --env POSTGRES_USER=postgres --env POSTGRES_PASSWORD=postgres pgvector/pgvector:pg16
```

The pulled image identity was
`sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
The actual server reported PostgreSQL **16.15** and pgvector **0.8.7**. Existing
team containers/databases were not used for evaluation.

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_pdf --backend local --output work/team-pdf-postgres.json
```

The runner validates frozen hashes before scoring. It copies precisely the 16
manifest files to `work/team-pdf-corpus`, verifies their bytes, and runs the
existing scan, PDF extraction/chunk persistence, keyword indexing and embedding
handlers. It re-parses even on repeat runs, preserving unchanged chunk IDs and
replacing any previously injected hand-authored text. The staged corpus and
database must contain exactly the manifest paths. Extra/missing/changed files,
wrong versions, absent pages and unready indexes produce explicit diagnostics.
It records parser outputs for abnormal files rather than forcing D's expected
statuses into B's production parser.

This is synchronous execution of the production handlers, and **does not prove
API-to-worker job dispatch**. PostgreSQL uses the actual Alembic chain ending at
`20261015_0002`, then explicitly creates C's token table with
`prepare_search_schema`. The original shared dense column and migration files
remain unchanged. An existing canonical database can prepare only the new
derived table with:

```powershell
.\.venv\Scripts\python.exe -m scripts.search_tools prepare-token-index --database-url YOUR_DATABASE_URL
```

This step does not populate vectors. Run the existing index command for each
current readable version afterward. SQLite is available for portable local checks:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_team_pdf --database-url sqlite:///work/team-pdf-off.db --backend off --output work/team-pdf-off.json
```

The current shared migration alters a nullable jobs column with PostgreSQL SQL
that SQLite cannot execute. A fresh SQLite database therefore uses the canonical
ORM metadata, explicitly reported as test schema rather than migration evidence.
An existing partial SQLite schema is refused and left unchanged. A must own any
change to that shared migration. An `off` run should exit 1: keyword can pass,
but the semantic candidate gate must fail. Likewise, a real model run below the
quality gate saves all results and exits 1; exit status alone is not a diagnostic.

## Frozen C configuration

| Parameter | Value |
| --- | --- |
| Model | `perplexity-ai/pplx-embed-v2-late-0.6b` |
| Revision | `7bba8e7cf2075dec747fa8557f41eb90e70361ed` |
| Representation | variable-length token matrices, 128 dimensions per token |
| Native prefixes | `[Q] ` and `[D] ` |
| Pooling / normalization | no dense pooling; L2 normalization per retained token |
| Input limit | first 2,000 chunk characters; native query/document limits 1,024/4,096 tokens |
| Request / model batch / CPU threads | up to 16 passages per request / up to 4 per model forward / 4 threads |
| Model device / dtype | CPU / float32 |
| Parser chunks | target 700 characters, overlap 120, minimum 80 |
| Query limits | 500 characters, 64 distinct search tokens |
| Keyword / semantic weights | 0.65 / 0.35, normalized by their sum |
| Candidate cap | 200 distinct files after choosing each file's best score for the requested mode |
| Evaluation / API top_k | 3 recorded (keyword scored at 1) / API default 10, maximum 50 |
| HTTP AI timeout | 10 seconds |
| Direct local inference timeout | no HTTP deadline; report distinguishes this path |
| Runtime network | local files / loopback AI service, no cloud fallback |
| Semantic search | exact MaxSim sum divided by query-token count; no separate reranker |
| Token storage | C-owned JSON / PostgreSQL JSONB sidecar, linked to canonical chunk IDs |
| Retired dense column | shared 384-dimension column preserved and unused |

This configuration is a C reproducibility candidate. It does not change the
historical `search-config-final.json` into a team freeze. Actual software versions,
model hashes, Git SHA and source file hashes belong to the dated evidence.

## AI failure and recovery

The public response field `mode` is the requested mode; `effective_mode`,
`degraded` and `degradation_reason` describe what ran. Disconnected HTTP AI returns
`ai_unavailable`, a request deadline returns `ai_timeout`, disabled AI returns
`ai_disabled`, and no compatible vectors returns `embeddings_not_ready`. Keyword
results and original evidence remain available. Partial vectors retain the
requested semantic/hybrid mode while reporting `partial_embeddings` and failing
the model evaluation gate.

The missing-sidecar readiness repair includes every eligible parsed chunk,
including chunks with no `chunk_search_index` row, in the same current-version,
authorized-root and presence scope. This prevents a partial index being reported
as complete. Tests cover active/paused/revoked roots, file/root intersection,
missing/unavailable files, newly discovered/old versions, and one hit per file.
Identical content at different paths remains separate files as required by the
shared contract; file deduplication does not delete source copies.

After restoring the local AI service, warm it once using a 120-second client
timeout so model initialization does not consume the normal search deadline:

```powershell
$warmup = @{ texts = @("warm up"); kind = "query" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8100/embeddings -Method Post -ContentType application/json -Body $warmup -TimeoutSec 120
.\.venv\Scripts\python.exe -m scripts.search_tools index --database-url YOUR_DATABASE_URL --version-id CURRENT_VERSION_UUID --backend http --ai-url http://127.0.0.1:8100 --timeout 10
```

Repeat the existing index command for each current readable version with missing
or incompatible vectors. Success requires `embedding_error=null` and
`embedded_count=chunk_count`; verify it with semantic/hybrid searches afterward.
Failure preserves keyword sidecars, source chunks and already published vectors.
Re-indexing does not require a new scan or different file/version/chunk IDs.
The direct `--backend local --model-path models/pplx-embed-v2-late-0.6b` form is
also supported for offline recovery. No recovery API/UI was added.

The integrated Worker currently marks an embedding job completed even when
`IndexResult.embedding_error` is non-null, retaining the failure only in logs.
Consequently `job.status=completed` does not establish vector readiness or an
automatic recovery retry. This is an A-owned follow-up; C leaves Worker behavior
unchanged and provides the existing operational backfill path.

For live protocol evidence, start from an `off` PDF evaluation database/report:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_team_search_runtime --database-url YOUR_DATABASE_URL --evaluation work/team-pdf-off.json --model-path models/pplx-embed-v2-late-0.6b --timeout 10 --output work/team-pdf-runtime.json
```

This tool starts temporary loopback API/AI processes, runs the existing index CLI
against every current parsed PDF version, records all 15 online searches and
their HTTP evidence, actually stops AI, induces a real delayed HTTP timeout,
restores the local model, and retries indexing. It saves raw responses and checks
source bytes/IDs throughout. It stops only its own helper processes.
The runtime report counts compatible chunk matrices separately from total token
vectors. Compatibility includes the new model/revision, 128 dimensions and the
source-text fingerprint. The model prewarm limit is 120 seconds and the index
subprocess limit is 180 seconds; normal search requests still use a 10-second AI
deadline. Those protocol checks do not convert a degraded result into a semantic
hit or establish a semantic-quality acceptance claim.

## Handoff to A, B and D

1. **A + B + D: choose a common corpus.** Compose mounts B's
   `tests/fixtures/regression` and three parsing fixtures, while D's frozen gold
   names `fixtures/normal/team-*`, `fixtures/abnormal` and the unsupported DOCX.
   They have different paths, hashes and page counts. This run evaluates the
   unchanged D corpus explicitly. An A-reviewed mount override can point both API
   and Worker to the staged exact D corpus. A gold for B's corpus requires a new
   version and B approval, never filename matching or rewriting this freeze.
2. **B + D: complete the pending human review.** Review every expected excerpt,
   page and acceptable source; determine whether ordinal placeholder questions
   should support any semantic-quality acceptance claim. Preserve current
   failures and publish a separately frozen topical PDF benchmark if needed.
3. **B + D: reconcile abnormal classifications separately.** The real parser
   reports four `unsupported` files here. D's manifest expects three `failed`
   files and uppercase mock error codes. The report records all four differing
   classifications. The retrieval denominator remains five queries per mode.
4. **A: provision pgvector and verified local weights**, use the same allowlist
   and read-only source mount for API/Worker, warm the model, inspect index
   completeness, and decide how failed embedding jobs should remain retryable.
5. **A: own SQLite migration portability and shared assembly.** C has not changed
   shared models, Alembic migrations, API assembly or Worker dispatch. The PDF
   handler runner does not replace integrated queue/restart/deployment checks.

The dated raw JSON and final validation summary are under
`submissions/week07/evidence/C/team-pdf-20261029/`. Each query records unchanged
expected locations, resolved current IDs, actual ranks/pages/chunks, degradation
and evidence. A failed candidate gate, B pending, corpus classification differences
and any unrun environment check must remain visible in the final report.

## Historical E5 validation on 2026-10-29 to 2026-10-30

The clean `.venv-clean` environment (Python 3.11.5, Torch 2.8.0, Transformers
4.57.1) produced keyword Top-1 **5/5**, semantic Top-3 **3/5**, and hybrid Top-3
**3/5**, on both PostgreSQL and SQLite. All 15 searches executed without
degradation, duplicate files or evidence failures. The semantic **4/5 C candidate
gate failed**; hybrid has no separate team-frozen acceptance gate. B review is
still pending and these placeholder PDFs do not establish topical search quality.

The live HTTP verification passed: 20 missing vectors were backfilled through
the existing index CLI; real disconnect and 10-second delayed-response probes
returned `ai_unavailable` and `ai_timeout`; keyword fallback and evidence remained
readable. Restoring AI and repeating indexing preserved all source/chunk IDs and
all 16 source hashes. Final tests: **349 passed, 2 skipped** (Windows symlink
privilege), with PostgreSQL tests enabled; Ruff passed. The dated evidence README
records exact commands, evaluated Git SHAs, complete Top-3 results and remaining
A/B/D dependencies. The older backup runtime and failed inherited-environment
warmup are retained separately and are not the final clean-environment results.
