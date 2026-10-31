# W7 integrated acceptance record

Audit date: 2026-10-31. Target branch: `feat/c-team-pdf-evaluation`.
Audit baseline: `0e3d715` (before the fixes and verification in this run).

The W7 implementation and automated integrated acceptance are complete for the
working tree recorded below. This run found and repaired defects, then executed
the real API/Worker/PostgreSQL/model/browser workflow. Human milestone sign-off
and B's gold review remain separate and have not been supplied by this audit.

## Requirement sources and scope

1. `templates/submissions/week07-README-template.md` defines the milestone report:
   working vertical slice, live demo, implementation status, DB/API/Worker/AI and
   operational evidence, verification, risks, next plan and AI use statement.
2. `docs/team11-w7-shared-contract.md` is the current integration contract. Its
   section 9.2 gives fifteen required integrated checks; sections 6 and 12 define
   the public fields, source refusals, retry behavior and authorization rules.
   Section 13 covers automatic local-model preparation and recovery indexing.
3. The Week 4 proposal remains the scope source, at commit
   `9e42e44d376c074083c4ebf2ca2b8e6ce6a5bf5e`, `docs/architecture.md`:
   line 19 defines the W7 text-PDF slice; lines 83 and 85 require local request
   protection and AI-independent startup; line 282 requires protection of writes.
   Those requirements apply to this slice, not only to a future remote product.

The proposal's API and queue designs were drafts. The current shared contract
narrows graph delivery to bounded source-backed relation candidates and persisted
review decisions; it does not require a new `/graph` or manual-tag route for this
integration. Its job vocabulary excludes `retry_wait` and `canceled`. The old
proposal's lease/crash-recovery scenario is a later queue work item under the
current single-worker W7 scope, not a claim that the present worker has leases.

## Execution identity

| Field | Result for this run |
| --- | --- |
| Tested commit and working-tree changes | `feat/c-team-pdf-evaluation`, baseline `0e3d715d75373f33ece45192fc3ae63cc4496de6` plus fixes that were uncommitted during verification; [identity and source hashes](../submissions/week07/evidence/20261031-w7/identity.json) preserve that snapshot. The verified changes were subsequently committed by topic. Remote push is left to the repository owner. |
| OS / Python / Node | Windows host, Python 3.11.5 / Node 22.23.1; final tests inside Linux/Python 3.11 image. Exact runtime versions are in `identity.json`. |
| PostgreSQL / extension versions | Real PostgreSQL 16.15 / pgvector 0.8.7, isolated Compose project and named volume. |
| Built image IDs and build command | `docker compose -p team11-w7-audit-20261031 -f compose.yaml -f work/w7-audit.compose.yaml build api worker ai`; image/container IDs and read-only mounts in `identity.json`; final test container has no source bind mount. |
| Model / revision / verified readiness | `perplexity-ai/pplx-embed-v2-late-0.6b` @ `7bba8e7cf2075dec747fa8557f41eb90e70361ed`, native query/document inference, 128-dimensional tokens. This run verified and reused the existing pinned cache; it did not repeat the download. |
| Corpus paths and SHA-256 manifest | `tests/fixtures/regression`, three abnormal PDFs in `tests/fixtures/parsing`, and `tests/fixtures/relations/entities.pdf`; before/after SHA-256 and sizes in `http-db-final.json`. Only copies under `work/w7-audit-sources` were changed in recovery tests. Frozen gold bytes remain unchanged. |
| Evidence directory | [20261031-w7 evidence index](../submissions/week07/evidence/20261031-w7/README.md), including commands, failures, repairs and final reports. |

Historical artifacts retain their original identities. In particular,
`submissions/week07/evidence/B/` records B's earlier combined pipeline and relation
checks, and `evidence/C/20261030-page-navigation/` and `20261030-startup/` record
C's earlier model/navigation/startup checks. They are supporting history, not a
substitute for executing the current combined tree.

## Acceptance matrix

| ID | Requirement and source | Test / execution entry point | Current-run result |
| --- | --- | --- | --- |
| W7-01 | One Alembic head; empty PostgreSQL upgrade, downgrade and upgrade (contract 7.2, 9.2.1-2) | `tests/integration/test_search_sidecar_migration.py`; disposable PostgreSQL databases | **PASS** — five migration tests, `w7-audit-migration.xml`, also included in final Linux suite. Corrected derived-sidecar downgrade FK order. |
| W7-02 | Mount/directory listing and atomic 202 root + pending job (9.2.3-4) | Real `/select`, `/mounts`, `/roots`; route/transaction tests | **PASS** — `http-db-final.json`; `frontend-live-clean/browser-live-report.json`. |
| W7-03 | Actual Worker scan → extraction → index produces canonical rows (9.2.5) | Empty-database browser import and real Worker/DB snapshot | **PASS** — `clean-database-before.json` has zero roots/files/jobs; clean browser 3/3; canonical 16 files/16 versions, 30 chunks/keyword rows, 12 ready + 4 handled unsupported. |
| W7-04 | New content updates current pointer; old content stays historical (9.2.6) | Real copied-source update/revert, scan/search tests | **PASS** — `backend-scenarios.json`, current pointer changes and content reversion reuses retained identity; historical rows remain. |
| W7-05 | Correct physical pages; bad files do not block neighbors (9.2.7) | Real mixed browser import; independent PyMuPDF source comparison | **PASS** — mixed browser 6/6; `runtime-safety-pages.json` verifies 30/30 chunks against physical page text, marker, hash and size. Reasons: corrupt/encrypted/no_text_layer/unsupported_format. |
| W7-06 | Keyword search works without AI (9.2.8) | Cold start without AI, fixed Marker gold, first-search browser test | **PASS** — `http-db-ai-unavailable.json` 202/0; fixed keyword Top-1 5/5. New empty-DB browser uses disabled AI and succeeds on one search. |
| W7-07 | Real semantic/hybrid search; explicit AI disconnect/timeout fallback (9.2.9) | Actual native PPLX requests and full-service disconnect; timeout/API/UI contract tests | **PASS** — `model-modes.json` ready/disconnected/restored all pass; semantic/hybrid explicitly become keyword while AI is stopped. Timeout cases pass in final suite; UI fallback covered by contract browser, not presented as live timeout execution. |
| W7-08 | Hit chunk retrieves the same version/page/passage (9.2.10) | Real browser/API evidence; physical-page and frozen-location checks | **PASS** — `http-db-final.json` checks all 30 chunks; clean/mixed browser source panels; independent 30/30 physical chunks and frozen 10/10 source locations. |
| W7-09 | Historical evidence 409; revoked-root evidence 403 (9.2.11) | Actual source mutation/deletion and scope refusal; API tests | **PASS** — `backend-scenarios.json`: historical/changed 409, deleted 404, revoked evidence/relations 403 and hidden search. Paused/revoked scope states are injected into isolated DB; no scope-management UI is claimed. |
| W7-10 | Automatic person/project/topic candidates, valid offsets, append-only confirm/correct/reject; stale review 409 (9.2.12) | Real relation PDF → `/graph` UI → `/review` UI and HTTP/DB validation | **PASS** — mixed browser saves all three decisions and reloads; final HTTP verifier validates direct chunk/version/page/quote, revision receipts, append-only rows and stale 409. Offset extraction tests pass. `/graph` here is the frontend route, not a new graph API. |
| W7-11 | Repeated scans do not duplicate files, versions, chunks, indexes or active jobs (9.2.13) | Compare persisted ID sets and added jobs before/after actual rescan | **PASS** — final HTTP report preserves all IDs and adds exactly one scan, zero extract/embed jobs; clean/mixed browser rescans pass. Completed model-recovery embedding history is allowed; duplicate live work is rejected. |
| W7-12 | Results and saved decisions survive normal restart (9.2.14) | Force-recreate DB/API/Worker/frontend containers, preserve volume | **PASS** — `restart.json`: all 12 durable table digests identical, three existing sources readable; before/after container IDs differ. Snapshot had 9 reviews; later verification legitimately appends more. |
| W7-13 | Original files unchanged (9.2.15) | Hash exact mounted originals; inspect source mount permissions | **PASS** — final HTTP 17-source before/after SHA-256 and sizes identical; model/scenario reports also verify originals; source mounts `RW=false` in identity. Recovery mutates copies only. |
| W7-14 | Failed source job is explicitly retryable; attempts retained (contract 12.3) | Real source-copy loss → restore → HTTP retry; recovery/dispatch tests | **PASS** — `backend-scenarios.json`: extract job 71 fails file_missing at attempt 1, rescan does not retry implicitly, explicit 202 reuses job 71, completes at attempt 2, unique first embed job 73. UI retry contract also passes. |
| W7-15 | Local Host/Origin protection; safe input refusals (proposal 83, 282; contract 4) | Real local allowed request and eight unsafe request classes; integration tests | **PASS** — `runtime-safety-pages.json` 102 checks/0 failures, eight unsafe classes rejected with no DB writes; final Linux also executes symlink and FIFO cases. |
| W7-16 | API/scan/keyword available when AI cannot start (proposal 85; contract 13) | Cold-start API/Worker without AI; independent health/search/evidence | **PASS** — AI absent during initial 202-check HTTP/DB run; empty-DB browser also passes with AI disabled; Compose no longer waits for AI health. |
| W7-17 | Setup progress, retry, true model readiness and missing-vector recovery (contract 13) | Native startup probe, live preparation/retry UI, background indexing recovery | **PASS** — `model-ready.json`, `model-browser.json`, `model-retry-browser.json`; real offline-cache error → Retry 202 → ready after cache repair. Existing cache reused, no new download claim. Canonical token rows recover automatically from 0 to 30 in `model-modes.json`. |
| W7-18 | Branch checks pass after rebuilt images; skips reported (contract 9.1) | Final image Ruff/Python + PostgreSQL; Node/Vitest/build; fixtures/gold | **PASS** — final Linux **744 passed, 0 skipped**, Ruff clean (`linux-final-tests.xml`, `w7-final-container-tests.log`); Vitest 56, Node 56, build and fixture/mock checks pass. Windows earlier 737/2 skips are historical; Linux executes both skipped OS cases. |

For every completion claim, record the tested commit, command, actual output,
database/extension and image versions (contract 9.3). SQLite tests establish
functional contracts; PostgreSQL and real Worker/browser execution establish the
deployment boundaries that SQLite and intercepted browser fixtures cannot.

## Corpus and evaluation boundaries

The mounted B/Compose corpus has twelve normal PDFs and four handled unsupported
records: `corrupt`, `encrypted`, `no_text_layer` and `unsupported_format`. D's
historical frozen `fixtures/manifest.json` uses a different corpus and obsolete
abnormal status/code expectations. Preserve its existing bytes and answers as
historical; any unified acceptance manifest must be a new version documenting
the actual source identities and outcomes. Do not alter expected pages after
observing retrieval output.

M1's historical targets include keyword 5/5, source-location 10/10 and at least
six unsafe-input refusals. The C semantic 4/5 target was a candidate rather than
a team-frozen gate. Navigation-assisted retrieval and pure-model retrieval must
be reported separately. Gold source verification, model quality and human review
are separate activities; automated checks do not sign B's gold review.

## Later scope and sign-off

W7 excludes OCR; DOCX/TXT/Markdown/image parsing; filesystem monitoring;
pause/resume management and scope purge/export; full graph traversal/layout;
multi-worker leases/backoff; move/rename and undo. These remain later R1/W13 or
stretch work as recorded in the proposal and contract section 11.

Current automated acceptance: **PASS, 18/18 gates**. Human A/B/C/D sign-off and
B gold review: **not supplied by this audit**. The implementation and tests may
be completed without inventing those human approvals.
