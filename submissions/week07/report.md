# Team 11 — Week 07 report

## Current integrated review: 2026-10-31

Target: `feat/c-team-pdf-evaluation`; audit baseline: `0e3d715`, before this
run's fixes. The current implementation combines scanning, extraction, automatic
relation candidates, source evidence and reviews, search, a real API-mode UI,
and automatic local-model preparation with recovery indexing. The former missing
route assembly, relation `chunk_id` and unspecified review-response blockers are
closed in code and in the shared contract. Human milestone sign-off is separate.

Current-run implementation and automated acceptance are **complete: 18/18 gates
pass** in [the acceptance matrix](../../docs/w7-acceptance.md). The
[evidence index](evidence/20261031-w7/README.md) records the tree as tested before
committing, exact commands, source hashes, PostgreSQL/extension and image versions,
preserved failures and subsequent repairs. Historical counts below belong to
their dated snapshots and are not totals for this working tree. The verified
changes were subsequently committed by topic; the repository owner will handle
the remote push.

Original integrated Linux/Python/PostgreSQL suite: **744 passed, 0 skipped**, Ruff clean.
Frontend in that snapshot: **56 Vitest and 56 Node tests passed**, production build passed.
The [current CI Node follow-up at `2b975a0`](evidence/20261031-w7/node-review-followup.json)
passed **62/62 tests** (56 contracts plus 6 browser-launcher regressions;
[output](evidence/20261031-w7/node-review-followup.tap)). This Node check did not
rerun the original runtime/image workflow below.
Real HTTP/DB: **202 checks/0 failures**; safety and independent physical pages:
**102 checks/0 failures**, 30/30 chunks. Empty-database browser first import,
single search/evidence and rescan passed; mixed import plus three review decisions
and reload persistence passed. Native PPLX semantic/hybrid, full AI disconnection
and restoration, setup/retry, missing-vector recovery and normal DB/API/Worker/UI
container recreation also passed. The existing pinned model cache was verified
and reused; this run did not repeat downloading.

The user-facing sequence is authorize a read-only directory, watch durable
background progress, search and inspect current source passages, inspect bounded
person/project/topic candidates, save a revisioned decision, exercise explicit
failure/retry and AI degradation, and verify persistence and unchanged originals.
The current new-install default is API mode. An existing explicit mock setting
remains a labelled simulation and does not provide real acceptance evidence.

This audit identified checks for AI-independent cold startup and local Host/Origin
protection from the original architecture, plus parser/UI/model-recovery edge
cases. Verified repairs include precise relation evidence/correction and receipt
validation, unreadable-source refusal, missing initial indexing dispatch recovery,
disabled-AI behavior, atomic keyword readiness, local request protection,
AI-independent startup, sidecar downgrade order and complete evaluation packaging.
The real browser exercises first import, repeated scan and mixed abnormal input;
DB identity sets prove rescan idempotency. The verifier also has regression tests
for legitimate completed model-recovery jobs and duplicate live work.

Two historical corpora remain distinct. B/Compose uses twelve normal PDFs plus
corrupt/encrypted/no-text-layer/unsupported-format inputs. D's frozen corpus has
different bytes and obsolete abnormal status/code expectations. Preserve old
freezes and answers, document any new unified acceptance version, and separate
pure-model retrieval from physical-page-navigation-assisted results. B's human
gold review and A/B/C/D signatures cannot be supplied by automated execution.

W7 remains the manual text-PDF slice with a bounded basic relation view and saved
reviews. OCR, other formats, monitoring, full graph exploration, purge/export,
multi-worker lease recovery and file organization remain later work. The shared
contract governs the current narrowed route and job vocabulary; old proposal
routes and its broader queue sketch are not newly claimed implemented features.

The [current README](README.md), [M1 checklist](m1-checklist.md) and
[scope record](scope-decision.md) supersede the current-status statements in the
historical report below. Original evidence files remain unchanged.

## Historical freeze report: 2026-10-23

The following sections preserve the draft prepared against `Role_D` at `ed1f307`
(22 October), including its historical counts, risks and limits. Statements such
as missing relation chunk IDs, a mock default or unassembled routes describe
that snapshot, not the current combined branch. No teammate's approval is
recorded or implied.

## 1. Project overview

Team 11 is building a local-first document assistant: a user authorises a read-only directory,
the worker scans it, the parser turns supported documents into per-page text with a stable byte
identity, the index makes that text searchable by keyword, by embedding or by a hybrid of both,
and every search result can be opened as a source passage that is bound to a specific file
version and page. Relation candidates extracted from the same evidence can be confirmed,
corrected or rejected by a human reviewer, and each decision is revisioned.

The system is deliberately local: source files are never copied, never modified, and never
uploaded. A scan authorization names a configured mount and a relative directory, not a host
path. Search runs against current content versions only. Evidence is version-bound, so a passage
can never be presented as current after its file has changed.

Work is split by role, and the split is enforced by file ownership rather than by convention:

| Role | Owns | Current branch |
| --- | --- | --- |
| A | Service assembly, mounts, roots, scan dispatch, worker wiring | `Role_A`, `w7-scan-dispatch` |
| B | Parsing, page evidence, relation extraction, review writes | `w7-parsing`, `fix/w7-b-evidence-review-followup` |
| C | Retrieval: keyword index, embeddings, hybrid ranking | `feat/c-search-model-evaluation` |
| D | Frontend, integration contract, fixtures, evidence, submission material | `Role_D` |

D's rule for the week was simple: consume the shared contract, never invent a backend, and never
present a simulation as product acceptance. Most of the disagreements in this report come from
holding that line while the backend was still being assembled.

## 2. Architecture as built

The stack is five Compose services plus one static frontend:

- `db` — `pgvector/pgvector:pg16`, the single source of truth for roots, files, versions, chunks,
  search index rows, relations and review records.
- `api` — FastAPI, synchronous SQLAlchemy sessions, health and metrics endpoints.
- `worker` — polls for jobs and drives scan and parse work.
- `ai` — embedding service for chunk and query vectors (`multilingual-e5-small`).
- `frontend` — React 18 + Vite built into an Nginx image, reverse-proxying `/api`.

The intended data flow is: authorize a root → 202 with `root_id` and `job_id` → worker enumerates
and parses → per-page text plus `content_sha256` per version → chunks and embeddings → search
returns chunks → evidence is read by `chunk_id` → relation candidates hang off a version →
human decisions append review records with an expected revision.

Two documents define the boundary. `docs/api-service-boundary-design.md` names the interfaces and
their failure modes; `docs/frontend-integration-contract.md` states exactly what the D consumer
reads, what it rejects, and which parts are still a proposal rather than an assembled route. The
second document is the one that matters for this report, because it is written to be falsifiable:
each paragraph says what the UI does when the backend disagrees.

What the `api` service actually assembles today is narrower than that boundary document:
`/health/live`, `/health/ready`, `/metrics`, the starter `/cases` routes, `GET /jobs/{id}`,
`POST /search`, `POST /roots` and `GET /roots/{id}`. It does **not** assemble `/mounts`,
`/mounts/{id}/directories`, `GET /files`, `GET /evidence/{chunk_id}`,
`GET /versions/{id}/relations`, `POST /relations/{id}/reviews` or `POST /jobs/{id}/retry`.
`services/parsing/graph.py` contains relation reads and review appends as functions, and the
worker contains the parse handlers, but a function existing is not a route being served.

That gap is the single most important fact in this report. It is why the frontend ships with an
explicit mock build, why every integration claim is scoped to the consumer layer, and why M1 is
recorded as not passed rather than partially passed.

## 3. What was delivered, by milestone

The week ran from 14 to 19 October, with a review and fix cycle on 21–22 October.

**10.14 — fixtures and document skeleton.** 16 synthetic files in `fixtures/`: 12 normal PDFs
across two team subdirectories, 3 abnormal PDFs, and 1 unsupported-format file. `manifest.json`
records file id, version id, relative path, SHA-256, page count, expected status and expected
error code for each. The normal corpus contains 20 traceable pages. The three UI skeletons
(select, scan, results) and a 12-slide outline were produced the same day.

**10.15 — authorization, progress, results.** The frontend gained the HTTP adapter, the request
lifecycle, and the progress model that keeps job state separate from root file-stage counters.
Authorization consumes a flat HTTP 202 `{root_id, job_id, status}` and rejects the starter's
nested `{id, status: "claimed"}` envelope rather than papering over it.

**10.16 — verification and honest boundaries.** Ten frozen gold queries (five keyword, five
semantic descriptions, English and Chinese) were checked against the actual PDF pages; all ten
locations resolve, and all sixteen corpus hashes match. Eight watermarked browser contract
scenarios ran against intercepted `/api` responses. The report and screenshots carry
`product_acceptance: false`. Two infrastructure findings were fixed in source: both health probes
used `127.0.0.1` because Alpine resolves `localhost` to IPv6 while Nginx listens on IPv4, and the
generated lockfile was committed so `npm ci` is reproducible.

**10.17 — search, chunk evidence, explicit retry.** The results page stopped treating the catalog
filter as retrieval and started calling canonical `POST /search`, with explicit keyword, hybrid
and semantic modes, visible requested-versus-effective mode, and a degradation reason. Evidence
moved from a per-file list to `GET /evidence/{chunk_id}` with file, version, page, ordinal and
path verification. Failed jobs gained an explicit retry action with 202 acceptance, identity
checks, duplicate-submission blocking, and no automatic replay.

**10.18 — acceptance honesty.** The M1 checklist records all three real scenarios as not run.
Nothing was fabricated to fill those rows: no invented job ids, no invented counters, no
signatures.

**10.19 — relations and human review.** `/graph` and `/review` became real consumer pages: up to
twenty candidates per version, provenance and revision displayed, source verification required
before a decision can be saved, confirm/correct/reject with an existing corrected entity id, and
optimistic concurrency via `expected_revision`. The 10.19 API-consumer browser report records 19
scenarios, and a separate mock-relations report records 5 scenarios with no HTTP interception.

**21–22 October — review and hardening.** An independent review of PR #5 found five issues. The
merge-blocking one was real and is fixed: `.gitignore` re-included an explicit list of files, so
`report.md` and other deliverables were silently invisible to `git status`. That block now allows
every week07 markdown file and whole `sections/` and `evidence/` directories, while personal
drafts stay ignored. Two documentation defects were fixed as well: the root README still claimed
API mode as the default after Compose moved to an explicit mock build, and the boundary document
named the review route `/relationships/{id}/reviews` instead of the agreed `/relations/{id}/reviews`.

D also fixed three defects found in its own code during the same cycle: the mock adapter labelled
a passage with the whole file digest; progress polling had no attempt budget; and a malformed
percent escape in the URL could blank the application. The mock now carries a per-chunk
`content_sha256` and fails loudly when it is missing, polling backs off from 900 ms to 5 s and
stops after 120 attempts with a visible resume control, and both a URL decode guard and a render
error boundary keep a failure recoverable.

## 4. Verification and evidence

Verification is split by what it can actually prove.

| Layer | What runs | What it proves |
| --- | --- | --- |
| Contract (Node) | 55 tests over adapters, progress, dedup, search lifecycle, review decisions | The consumer accepts and rejects the documented shapes |
| Component (Vitest) | 24 tests, including 12 React workflow tests | Race handling, replay protection, source verification, render containment |
| Build | `vite build`, 4917 modules | The frontend compiles from a clean install |
| Fixtures | `validate_d_fixtures.mjs`, 16 files, 20 pages | The corpus matches its manifest hashes |
| Frozen answers | `validate_d_gold.py`, 10 queries, 16 hashes | Every expected answer still resolves to its PDF page |
| Browser (intercepted `/api`) | 19 + 5 scenarios, watermarked | The UI survives the documented responses |
| CI | `test`, `nodescripts`, `frontend` on every push | The above run automatically, not by hand |

The CI jobs are new this week. Before them the frontend had no build and no test coverage in the
pipeline: a broken JSX file would only have failed at `docker build` time. The `test` job keeps its
name so the existing required check does not disappear.

Two honesty constraints apply to this table. First, the browser scenarios intercept `/api`; they
prove the consumer, not the service. Second, the gold check verifies that frozen answers still
locate their source pages; it does not measure retrieval quality, and the human review of those
answers is still pending.

Evidence lives under `submissions/week07/evidence/`. The 32 watermarked screenshots are **not**
versioned — they were 5.9 MB of PNGs for a text-only deliverable — and can be regenerated with
`node scripts/capture_d_ui.mjs`, `node scripts/capture_d_1019.mjs` or
`node scripts/capture_d_relations_mock.mjs`. Each report keeps its scenario names, and each
evidence README says the images are local-only.

## 5. Risks and open issues

| Id | Risk | Severity | Owner | Current state |
| --- | --- | --- | --- | --- |
| R1 | Seven file-management, evidence, relation and retry routes are not assembled | P0 | A / B | **Closed 2026-10-23** - merged in PR #6; all seven served |
| R2 | Fixture error codes do not match the parser's taxonomy | P1 | B + D | Reproduced and documented; fix needs a re-freeze |
| R3 | M1's three real browser scenarios have never been run on a clean database | P0 | A+B+C+D | Recorded as not run, deliberately not simulated |
| R4 | Relation candidates carry no addressable chunk id | P1 | A / B | D disables review when the quote cannot be located |
| R5 | Review success envelope (`200` + `decision_revision`) is D's expectation, not an agreed contract | P1 | A / B | Consumer fails loud on any other shape |
| R6 | Screenshots are no longer in version control | P2 | D | Regenerable by script; READMEs updated |

R2 deserves detail because it was misreported as a simple case mismatch. Running
`services/parsing/pdf.py` against the four non-ready fixtures gives:

| Fixture | Manifest expects | Actual reason code |
| --- | --- | --- |
| `abnormal/empty.pdf` | `EMPTY_FILE` | `unsupported_format` — zero bytes fails the `%PDF-` magic check |
| `abnormal/truncated.pdf` | `TRUNCATED_PDF` | `corrupt` |
| `abnormal/corrupt.pdf` | `CORRUPT_PDF` | `unsupported_format` — the placeholder is not a PDF either |
| `unsupported/*.docx` | `UNSUPPORTED_FORMAT` | `unsupported_format` |

Three of the four expected codes never occur, and one does not even correspond to the file it
names. Worse, `services/parsing/handler.py` records every `UnsupportedDocument` as
`VersionStatus.UNSUPPORTED`, so all four land as `unsupported`, never `failed`. The demo's
"12 normal / 3 failed / 1 unsupported" story would be 12 / 0 / 4 against the real pipeline.

Fixing that is not a rename. Changing the fixture bytes invalidates `gold-queries.freeze.json` and
the corpus hashes recorded in both gold-source-check evidence files, and it pulls the mock
counters, the acceptance table, the slide outline and the Node assertions along with it. It is a
cross-role taxonomy decision, so it is scheduled after the freeze with the abnormal set
regenerated as `corrupt` / `encrypted` / `no_text_layer` and lowercase codes throughout.

## 6. Overall status, risks, and readiness assessment

The honest summary on 21 October was a working set of vertical slices and no working end-to-end
chain. Since 23 October that has changed: the seven missing routes were assembled and merged
(PR #6), and one chain now runs from choosing a folder to reading the source passage behind a hit.
The assessment below keeps the original reading, then records what closed and what did not.

Each slice is real. Retrieval exists and is tested at the service level. Parsing produces
per-page text with a byte identity and distinguishes encrypted, corrupt, unreadable and
no-text-layer documents. The worker dispatches scan and parse work. The frontend authorises a
directory, polls a job, renders per-file state, searches content, opens version-bound evidence,
and records human decisions with optimistic concurrency. The contracts that connect them are
written down and enforced at runtime: the frontend rejects a response that claims 202 over HTTP
200, rejects a nested job envelope, rejects evidence whose page or version does not match, and
refuses to render a cached passage once its source is known to be invalid.

With the routes assembled, that gap is closed. The service now serves the mount, root, file, job,
evidence, relation, review and search endpoints the frontend calls, and an API-mode build runs
against it: 16 fixtures became 12 readable documents and 4 recorded refusals, a rescan added
nothing, and the original files' hashes were unchanged before and after. The default build still
ships the labelled simulation, because a demo that opens to an error page teaches a reviewer
nothing - but API mode is now a path that works, not an aspiration.

The verification story is stronger than the integration story, and both matter. On the consumer
side the numbers are unglamorous but load-bearing: 55 contract tests, 24 component tests, a
4917-module production build, 16 fixture hashes, 10 frozen answer locations, and 24 browser
scenarios across two reports. Three of those layers are now enforced by CI on every push, which
means the frontend can no longer rot silently between demos. On the service side, the Python
pipeline has unit and integration tests that run against a real Postgres with pgvector, and the
gold check runs in the same job. What remains missing is not wiring but operational maturity: one
worker, no claim lease, no backoff and no filesystem watcher. An endpoint that exists without a
test is still a rumour, which is why the new routes shipped with their own integration tests and
the queue invariants with PostgreSQL concurrency cases.

Two named risks decide the freeze, and one has since closed. The assembly gap (R1) is closed: the
seven routes are served and the frontend consumes them in API mode. What remains is acceptance
(R3) and taxonomy (R2). Acceptance needs the three M1 scenarios run in one unbroken sequence on a
clean database with recorded task ids, counts and signatures; the service half of that sequence is
now measured, the browser half with signatures is not, and the team still declines to substitute
intercepted requests for it. Taxonomy (R2) stands: the abnormal fixtures describe a vocabulary the
parser does not implement, so the "12 / 3 / 1" story would really be 12 / 0 / 4.

There is an encouraging pattern in how these were handled. When the reviewer pointed at
`.gitignore`, the fix was a two-line rule change plus an exit-code matrix proving which paths are
now visible and which stay ignored. When the reviewer pointed at the fixture codes, the response
was to run the parser and publish the actual mapping, including the part where the review's own
table was wrong. When the reviewer pointed at the README, the text was corrected rather than
argued with. That is the behaviour a team wants at a freeze: cheap fixes land immediately, and
expensive fixes get a written rationale and a date instead of a rushed patch.

For the freeze itself, the honest record is that the service path is measured and the browser
acceptance is not. Declaring M1 fully passed on the strength of intercepted browser fixtures would
be a false claim that survives in the repository forever; declaring the service half unproven would
now be unfair to it. The demo script can be replayed without interception, and the evidence files in
this folder were regenerated against the real service with recorded commit ids.

One point belongs here because it is easy to lose in a status table: for most of the week the gap
was not evenly distributed. Retrieval, parsing and the consumer layer were close to complete while
assembly sat with one role. That reading was right, and it also predicted how the week ended - the
assembly landed as one focused pull request rather than as four roles finishing together.

What "done" required was small and unglamorous, and most of it is now done: `/mounts` and
`/mounts/{id}/directories` are served; `GET /files?root_id=`, `GET /evidence/{chunk_id}`,
`GET /versions/{id}/relations` and `POST /relations/{id}/reviews` are served; retry is
`POST /jobs/{id}/retry` guarded by a conditional state update; and `POST /roots` returns the flat
envelope the consumer contract asks for. What is left from that list is the fixture re-freeze and
the signed three-scenario run.

The final judgement is therefore split, and the split is narrower than it was in October. Delivered
and verified: the consumer layer, the contracts, the fixtures, the assembled service, the scan and
parse and index path, and the evidence discipline. Not delivered: a filesystem watcher, multi-worker
safety, OCR, move detection, purge, and a signed browser acceptance run. Reported honestly: both of
those lists, in the same document, with the evidence that supports each.

## 7. Role contributions

### A - mounts, scanning, versions, jobs and the API surface

A's work across the week, in the order it mattered:

1. **The scan transaction.** Discovery walks an authorized folder without following symlinks,
   hashes each file, reuses the version when the bytes are unchanged, and moves
   `current_version_id` in the same transaction that queues `extract_file`. A rescan of unchanged
   content creates nothing.
2. **Pointer semantics.** The pointer means "latest content observed". A revert therefore has to
   move it back: leaving it on the revised version served superseded text as current while the
   file on disk was the old one. That was the review's blocking defect, and the fix is a two-line
   branch with a test that asserts no version is created.
3. **The mount and route surface.** Allowlisted read-only mounts, canonical containment,
   `404 unknown_mount`, `403 path_out_of_scope`, and the seven routes the browser needed:
   `/mounts`, `/mounts/{id}/directories`, `GET /roots`, `POST /roots/{id}/scans`,
   `POST /jobs/{id}/retry`, plus the flattened `POST /roots` and the counts-carrying
   `GET /roots/{id}`.
4. **Queue correctness.** Claim-and-enqueue runs under a root row lock; retry is a conditional
   `UPDATE ... WHERE status = 'failed'` so a stale read cannot reset claimed or completed work;
   paused, revoking and revoked roots are refused at every entry point. Six PostgreSQL concurrency
   cases cover these, each mutation-checked by removing the guard.
5. **Evidence discipline.** `scripts/w7_evidence_probe.py` drives the public API only, so the
   numbers in `evidence/` are what a client could observe: 16 files to 12 ready and 4 refusals,
   zero duplicates across eleven scans, and unchanged hashes across a restart and a container
   recreation.

### D - frontend, consumer contract and milestone materials

D's work across the week, in the order it mattered:

1. **Fixtures.** 16 synthetic files with a manifest of ids, hashes and expected outcomes, plus a
   deterministic generator (`scripts/generate_d_fixtures.mjs`) so the corpus can be rebuilt byte
   for byte.
2. **Consumer contract.** `docs/frontend-integration-contract.md` states the minimum response
   shapes, the rejection rules, the retry and no-replay policy, and the parts that remain
   proposals. It is the document that made an independent review possible.
3. **Adapters.** A strict HTTP adapter that validates every field it reads and fails closed with
   `CONTRACT_MISMATCH`, and a mock adapter that simulates the same contract without ever being
   selected by a runtime failure.
4. **UI.** Five routes (select, scan, results, graph, review), 24 component tests, and a render
   error boundary.
5. **Evidence discipline.** Frozen answers, gold location checks, browser contract reports with
   `product_acceptance: false`, and watermarked screenshots that are regenerable rather than
   committed.
6. **Process.** CI coverage for the frontend, an independent review cycle on PR #5, and a written
   response to every review item including the one that was deferred.

The most useful thing D learned is that a consumer contract is only credible when it specifies
failure. The adapter's value is not that it reads `root_id`; it is that it refuses to invent one.

## 8. Appendix — how to reproduce the current numbers

```powershell
# contract + component
node --test scripts/test_d_integration.test.mjs scripts/test_d_search_review.test.mjs
cd frontend; npm ci; npm run build; npm test -- --run

# fixtures and frozen answers
node scripts/test_d_mock.mjs
node scripts/validate_d_fixtures.mjs
python scripts/validate_d_gold.py

# browser contract reports (writes screenshots under submissions/week07/evidence/)
node scripts/capture_d_1019.mjs
node scripts/capture_d_relations_mock.mjs

# A: scan, security, M1 and restart evidence
python scripts/w7_evidence_probe.py --out submissions/week07/evidence/scan-run.json
docker compose exec -T db psql -U postgres -d maie6000c -c "select count(*) from file_versions;"

# A: the six PostgreSQL queue cases (concurrent rescan, duplicate authorization, stale retry)
SEARCH_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:15432/maie6000c \
  pytest tests/integration/test_api_queue_postgres.py -q
```

Evidence index: `submissions/week07/ui-progress.md`,
`submissions/week07/m1-checklist.md`, `submissions/week07/scope-decision.md`,
`submissions/week07/ui-acceptance.md`, `submissions/week07/evidence/1016-D/`,
`submissions/week07/evidence/1019-D/`.
