# C first-start initialization validation — 2026-10-30 (UTC)

The latest available develop was integrated into `feat/c-team-pdf-evaluation` at
`f6f347abad37345f0119c45b3913ce3ca1b6f5b6` (fast-forward). At validation capture, the
implementation below was uncommitted and unpushed; the recorded HEAD identifies the
integrated test base, not the subsequent feature commit. The JSON status fields are
point-in-time observations retained with their original capture timestamps.
[implementation-files.json](implementation-files.json) records the 45 changed/new implementation
files and their working-tree SHA-256 identities. Original main checkout and other roles'
branches were not changed. PR #8 was already merged and was not updated.

## Delivered behavior

Run `python scripts/start.py` from this C worktree. Python's standard library plus
installed/running Docker Desktop with Compose v2 are the host prerequisites. The launcher
preserves an existing `.env`, installs runtime/frontend dependencies inside images,
starts the real stack, then displays actual preparation stages. It never silently
installs machine-wide Docker, changes host Python packages or needs a GitHub token.

The AI background task downloads only 14 pinned public model files, verifies their
fixed SHA-256 identities, atomically publishes verified files/manifest, loads the CPU
model and performs real query AND passage warmup before declaring ready. Downloads
are resumable, bounded, cancellable and cross-process locked. Offline/auto-prepare
disable controls remain explicit. Verified-cache reuse does not instantiate a
network client.

The real frontend shows backend status, measured bytes/file counts, errors and explicit
Retry. Unknown overall progress remains indeterminate. Dependency/build output is
available in the terminal before the frontend image exists; the UI does not claim to
display progress before it can run. Existing explicit mock mode remains labelled mock.

During preparation/failure, normal PDF parsing, keyword retrieval and original evidence
remain available. Model readiness is distinct from document-vector readiness. The Worker
automatically queues normal embed jobs on readiness for current, present, identity-verified
versions in active roots lacking compatible vectors. Old/revoked/paused/missing sources
and existing live jobs are excluded; PostgreSQL version-row locks serialize recovery
with ordinary dispatch. No separate recovery API is required.

Startup uses the shared Alembic chain including B's `20261030_0005`; it does not add a
competing implicit schema initializer. Source corpus mounts stay read-only; only the
AI's model cache is writable. Published ports are loopback-only.

## Actual deletion and cold download

The exact existing C model directory
`models/pplx-embed-v2-late-0.6b` was inspected and removed before the test:
15 files / 2,397,844,380 bytes, no linked entries, then confirmed absent.
These deletion observations were recorded during execution, not reconstructed from a
later successful status. Only this model directory was removed. It has now been
restored through the actual download; PDFs, other model caches and database volumes
were not deleted.

[startup-cold.json](startup-cold.json) is the raw run record:
`2026-10-30T16:40:02.312437+00:00` to `2026-10-30T16:44:06.641559+00:00`.
It records 34 status observations, 14/14 files and **2,397,842,839 payload bytes**,
through downloading → verifying → loading → warming_up → ready.

All **11/11** checks passed: liveness during preparation, readiness remaining 503,
ready after warmup, real query inference, real passage inference, automatic early-scan
vector recovery, required download observed, ready observed, keyword availability,
explicit semantic fallback and unchanged original source hashes (13 entries).

The normal scan used `tests/fixtures/regression`, not manual database chunks.
A request for `doc01` with top_k=3 returned one matching file, so its actual denominator
is one returned hit, not three fabricated hits:

| Stage | Requested / effective mode | Degraded | Actual rank / page | Chunk / version |
| --- | --- | --- | --- | --- |
| During preparation | semantic / keyword | true (`ai_unavailable`) | 1 / 1 | `df841df1-9470-4784-a8e1-45b910334066` / `77102c9f-3001-4608-8e60-9754c7bd5890` |
| After automatic recovery | semantic / semantic | false | 1 / 1 | same verified chunk/version |

The keyword score was 0.25; recovered token MaxSim mean was 0.62643. File was
`group-a/doc01.pdf`, file ID `79f55b2a-8705-4899-9476-60546c8591af`.
Both early and recovered evidence endpoints matched the corresponding chunk, version,
page and original text. Complete responses are in the JSON. The transient
`last_observation_error=RemoteProtocolError` is retained; the final checks recovered
and passed. This is not a claim that no transient error occurred.

## Real browser failure/retry and local reuse

[startup-browser.json](startup-browser.json) proves the real ready panel, not the entire
cold-download UI sequence: the browser began after the actual download had finished.
The API timeline above is the evidence for the real download.

For a genuine failure/retry test, only the 238-byte `1_Dense/config.json` was temporarily
moved to an ignored work backup. The isolated AI was restarted with auto-prepare disabled
and both offline flags enabled. The UI showed `local_model_missing_or_corrupt`.
After restoring the file and verifying SHA-256
`b2edb3cf8fbbd76ed3b41ed1e41bcb49c2fb4863a600914a70e30ba5dc5cef02`,
the browser clicked Retry once: actual HTTP **202**, checking_environment → model check →
verification → loading → warmup → ready, **no downloading**.

[startup-browser-retry.json](startup-browser-retry.json) contains all 113 actual status
responses and zero page errors. Its intermediate screenshot has `stage:null` because
the older image lacked the later `data-state` attribute; panel text and the HTTP
receipt prove checking_environment. The raw record was not rewritten to hide this.
Screenshots remain in the original work directory, as referenced by the raw JSON.

Normal automatic preparation has been restored. [startup-warm-launch.log](startup-warm-launch.log)
shows dependency-layer cache reuse and a verified local model reload without download;
it DID rebuild changed application/UI sources. Separately,
[startup-unchanged-launch.log](startup-unchanged-launch.log) shows the subsequent unchanged
launch skipping build entirely, reusing installed images and immediately returning ready.

## Model/runtime configuration (unchanged retrieval)

- Model: `perplexity-ai/pplx-embed-v2-late-0.6b`.
- Revision: `7bba8e7cf2075dec747fa8557f41eb90e70361ed`.
- Native query/document encoding, prefixes `[Q] ` / `[D] `, 128 dimensions per token;
  mean token MaxSim scoring, no pooling into the retired 384-dimensional shared column.
- Existing 2,000-character chunk input limit; model query/document limits 1,024/4,096 tokens;
  API batches ≤16, model forward batch 4; CPU threads 4.
- Weights keyword/semantic 0.65/0.35; per-channel file candidate limit 200;
  normal default top_k 10, maximum 50; this startup smoke requested 3.
- Search timeout 10 s; preparation network-operation timeout 30 s; retries 3.
- Actual container: Python 3.11.18, Torch 2.8.0+cpu, Transformers 5.22.0,
  Sentence Transformers 6.2.0, Hugging Face Hub 2.4.0.
- Runtime inference uses local files only. No hosted/cloud inference fallback.
  Dependency versions above are observed versions, not a claim of a fully locked
  transitive dependency graph.

## Commands and validation

Working directory:
`D:\HKUST AIE\MAIE6000C\MAIE6000C-starter-TEAM_11\tmp\c-team-pdf-evaluation`.

The isolated project uses these environment overrides; other project containers/volumes
were not operated on:

```powershell
$env:COMPOSE_PROJECT_NAME='team11-c-startup-20261030'
$env:API_HOST_PORT='18080'
$env:AI_HOST_PORT='18180'
$env:FRONTEND_HOST_PORT='13000'
$env:POSTGRES_HOST_PORT='15480'
$env:FRONTEND_DATA_MODE='api'
$env:EMBEDDING_AUTO_PREPARE='true'

python scripts/start.py --timeout 120 2>&1 | Tee-Object -FilePath work/startup-unchanged-launch.log

$env:SEARCH_TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:15480/team11_c_startup_tests'
.\.venv-pplx\Scripts\pytest.exe -q tests/unit tests/integration --tb=short --basetemp=work/pytest-startup-review-final-green-20261030 --junitxml=work/startup-full-postgres.xml
.\.venv-pplx\Scripts\ruff.exe check .
git diff --check

# From frontend/
npm test -- --run --reporter=json --outputFile=../work/startup-vitest-final.json
npm run test:integration
npm run build
```

Cold-record capture can be reproduced with the same recorded endpoints/options below,
started while a genuinely missing-model AI is preparing. This is a reproduction command;
the timestamped JSON, not an invented shell transcript, is the original run evidence:

```powershell
.\.venv-pplx\Scripts\python.exe scripts/verify_model_startup.py --api-url http://127.0.0.1:18080 --ai-url http://127.0.0.1:18180 --require-download --exercise-corpus --source-root tests/fixtures/regression --output work/startup-cold.json
node scripts/verify_startup_browser.mjs
```

The test database `team11_c_startup_tests` was created separately, with pgvector enabled;
the cold-scan application database `maie6000c` was not reused by destructive test fixtures.

| Validation | Result | Raw artifact |
| --- | --- | --- |
| Complete backend unit + integration, actual PostgreSQL/pgvector | **703 passed / 705 total**, 2 skipped, 0 failures/errors, 272.073 s | [JUnit](startup-full-postgres.xml) |
| Windows Git encoding/related regression | 57 passed | [JUnit](startup-encoding-regression.xml) |
| Frontend Vitest | 48/48 passed | [JSON](startup-vitest-final.json) |
| Frontend Node contracts | 55/55 passed, none skipped | [log](startup-node-final.log) |
| Production frontend build | passed, 4919 modules | [log](startup-frontend-build-final.log) |
| Whole-repository Ruff / whitespace | passed | final command outputs |

The two backend skips are Windows file-symlink privileges and Windows FIFO support,
not PostgreSQL or model unavailability. Ten existing dependency deprecation warnings
remain. The new PostgreSQL recovery-concurrency test actually ran and passed.

Older work reports `startup-full-sqlite.xml` (four pre-fix Windows GBK failures) and
`startup-full-postgres-pre-extension.xml` (six missing-extension environment errors)
are preserved but are NOT the final green evidence. Git decoding was fixed, pgvector
was initialized in the isolated test database, and the full suite above was rerun green.

## Scope, handoff and limitations

- This is initialization/recovery validation, not a new semantic gold evaluation.
  Historical pure PPLX 3/5 and navigation-assisted results remain historical, separately
  reported. No degraded result is counted as a semantic quality hit.
- Frozen gold, freeze files and tracked PDFs are unchanged. Gold identities are in
  [validation-summary.json](validation-summary.json); scanned-source hashes are in
  [startup-cold.json](startup-cold.json). Tracked PDFs and freeze files have no Git diff.
  B human gold review stays
  pending; C's ≥4/5 semantic candidate threshold is not newly team-frozen by this work.
- A: deployments still need Docker/Compose, disk/network access for the first image/model
  build, the existing shared migration chain, writable model-cache mount and the Worker.
  Model-ready does not mean all document jobs are finished.
- B/D: unified real-topic blind testing and gold human review remain independent follow-up
  dependencies; no answer/source files were adjusted to improve a score.
- The isolated stack is left running for inspection at
  [http://127.0.0.1:13000/select](http://127.0.0.1:13000/select);
  API 18080, AI 18180, database 15480. No volume deletion was performed.
- Stop only this test project if desired with
  `docker compose -p team11-c-startup-20261030 down` (never add `-v` for a normal stop).
- Text artifacts are copied as UTF-8/LF with a terminal newline; archived terminal logs
  also have trailing horizontal whitespace removed. Both original-work and bundled hashes
  are recorded in the summary; original work artifacts remain available.
  No credentials, weight files or source PDFs are included in this evidence bundle.

See [model startup guide](../../../../../docs/model-startup.md) for the ordinary
first-start command, setup endpoints, offline controls and operator retry procedure.
