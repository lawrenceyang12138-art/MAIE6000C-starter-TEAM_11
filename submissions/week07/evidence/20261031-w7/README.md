# W7 verification evidence — 2026-10-31

This directory records verification of `feat/c-team-pdf-evaluation` against an
isolated API/Worker/PostgreSQL/AI stack and real browser sessions. The source PDF
fixtures were mounted read-only. Reports include their observations and source
hashes; they should be read together with the limitations below.

Verification preceded the topic commits. `identity.json` retains the original
baseline and dirty-tree snapshot; its source hashes identify the tested code.
The verified changes were subsequently committed by topic, with remote push left
to the repository owner. Referenced text logs are included in Git; screenshots
follow the existing local-only evidence-image rule.

The original integrated run's runtime verifier passed **202 checks with zero failures**. Its final
Linux image passed **744 backend tests with zero skips**, plus Ruff. Frontend
Vitest passed **56 tests**, the then-current Node suite passed **56 tests**, and the
production build succeeded. These establish implementation and workflow
behavior. This directory's frozen-gold check verifies source locations, without
claiming a new retrieval-quality score. B's human gold review remains pending;
the shared W7 contract does not freeze a semantic-quality score as a release gate.

The current CI Node suite was rerun at `2b975a0`: **62 passed, 0 failed, 0 skipped**
(the original 56 contract tests plus 6 browser-launcher regression tests). See
[the follow-up output](node-review-followup.tap) and
[execution identity, command and source hashes](node-review-followup.json).
Only the launcher Python files had pending edits when this Node check started;
the tested Node sources matched that commit. This follow-up does not rerun or
replace the original Linux/backend/model/browser evidence.

## Final runtime and browser evidence

| Evidence | What it establishes |
| --- | --- |
| [identity.json](identity.json) | Baseline plus dirty working-tree identity, source hashes, actual container/image IDs and runtime versions. The final API image matches 156 source files; the already-running verified AI matches its eight AI/common files. Source mounts are read-only and the final test container has no source mounts. |
| [final-validation.json](final-validation.json) | Final consistency check: 22 checks passed, all 18 matrix gates have evidence, 68 documentation links resolve, final JUnit reports 744/0 skips, frozen inputs match the baseline and API/AI/UI remain ready. |
| [http-db-final.json](http-db-final.json) | Final real HTTP/Worker/PostgreSQL verification: 202 passed, 0 failed. Includes import, search, evidence, relations/reviews, rescan stability and persisted data checks. |
| [http-db-ai-unavailable.json](http-db-ai-unavailable.json) | Earlier real-stack run with AI unavailable: 202 passed, 0 failed; the keyword fallback remained usable. |
| [runtime-safety-pages.json](runtime-safety-pages.json) | 102 passed, 0 failed. Eight unsafe/unsupported input refusals produced no persistent writes. An independent PyMuPDF reader verified physical page numbers, text and hashes for all 30 observed chunks. |
| [backend-scenarios.json](backend-scenarios.json) | 38 recorded events covering version changes and rollback, old-version 409, unscanned source changes, missing-source 404, paused/revoked roots, append-only confirm/correct/reject reviews and revision conflicts. Real file disappearance followed by HTTP retry increased attempts from 1 to 2 while retaining IDs. Version and recovery checks passed. |
| [frontend-live-clean/browser-live-report.json](frontend-live-clean/browser-live-report.json) | Final first import into a clean database, through the real UI at port 13002: three cases passed for `scenarios/normal12-fresh`, 12 normal PDFs and 0 unsupported files. Keyword search, source evidence and stable rescan succeeded. |
| [frontend-live-fresh/browser-live-report.json](frontend-live-fresh/browser-live-report.json) | Additional first import into a new directory after the indexing repair: three real browser cases passed at port 13001. |
| [frontend-live-mixed/browser-live-report.json](frontend-live-mixed/browser-live-report.json) | Six real browser cases passed at port 13001: corpus import with 16 discovered files/4 unsupported files, search/evidence/rescan, and all three relation-review actions with reload persistence. |
| [restart.json](restart.json) | Before/after container recreation snapshots match across 12 database tables, including the nine reviews present at that snapshot. Later verification appended more reviews; nine is not the current review count. |
| [restart-containers-before.txt](restart-containers-before.txt), [restart-containers-after.txt](restart-containers-after.txt) | Container identities accompanying the restart comparison. |

The clean first-import browser report is the authoritative closure for the
initial keyword-indexing race. The older `frontend-live-normal` rescan report
alone only demonstrates behavior for data already imported.
After verification the extra clean-browser stack at port 13002 was stopped to
save resources; its database volume remains. The main demo at port 13001 remains
running. Its actual API image matches the final test container; AI remained on
its earlier verified image while verifier-only changes rebuilt API/Worker.

## Local model preparation, retry and fallback

| Evidence | What it establishes |
| --- | --- |
| [model-ready.json](model-ready.json) | Real loading, warmup and query/document inference using the fixed PPLX model revision. This run reused a complete existing cache and set `require_download=false`; it did **not** perform a new cold download. The `required_download_observed=true` check is vacuous with that flag disabled. |
| [model-browser.json](model-browser.json) | Real browser preparation progress reached `ready`. |
| [model-retry-browser.json](model-retry-browser.json) | Real browser error state, explicit retry, and successful recovery to `ready` using the repaired offline cache. |
| [retry-after-cache-repair.json](retry-after-cache-repair.json) | HTTP 202 receipt for the explicit preparation retry. |
| [model-modes.json](model-modes.json) | Real keyword/semantic/hybrid behavior while ready, degradation while the AI service was disconnected, and recovery after reconnecting. All three stages passed; all 30 chunks regained vector coverage automatically. |

The startup PNGs and browser output directories accompany the JSON observations.
Screenshots follow the repository's existing evidence-image ignore rule and may
remain local rather than being included in Git.

## Automated checks and packaging

| Evidence | Result |
| --- | --- |
| [linux-final-tests.xml](linux-final-tests.xml), [w7-final-container-tests.log](w7-final-container-tests.log) | Authoritative final Linux image run: Ruff passed; 744 tests passed, 0 skipped. Includes PostgreSQL-backed integration checks. Tests ran from the built image without binding the host source tree over it. |
| [w7-final-vitest.log](w7-final-vitest.log) | 5 test files, 56 tests passed. |
| [node-review-followup.tap](node-review-followup.tap), [node-review-followup.json](node-review-followup.json) | Current CI Node suite at `2b975a0`: 62 passed, 0 failed, 0 skipped; 56 existing contracts plus 6 browser-launcher tests. Metadata records command, host, pending edits and source hashes. |
| [w7-final-node.log](w7-final-node.log) | Historical integrated-run snapshot before the 6 browser-launcher tests: 56 passed, 0 failed, 0 skipped. |
| [w7-final-frontend-build.log](w7-final-frontend-build.log) | Production frontend build succeeded. |
| [w7-audit-migration.xml](w7-audit-migration.xml) | 5 migration tests passed, including downgrade/upgrade with populated keyword sidecar data. |
| [w7-final-image-build.log](w7-final-image-build.log), [w7-audit-packaging-build.log](w7-audit-packaging-build.log) | Image and evaluation-asset packaging build records. |
| [fixture-checks.log](fixture-checks.log), [mock-adapter-checks.log](mock-adapter-checks.log) | Fixture and mock-adapter consistency checks. |
| [w7-audit.compose.yaml](w7-audit.compose.yaml), [w7-clean.compose.yaml](w7-clean.compose.yaml), [w7-retry.compose.yaml](w7-retry.compose.yaml) | Isolated verification stack configuration, separate empty-database browser stack and retry-harness override. |

The final backend run reports dependency deprecation warnings; no tests failed or
were skipped. Earlier host/Linux results such as `w7-audit-final.xml`,
`linux-tests.xml` and `w7-verified-container-tests.log` are historical snapshots;
the final Linux report above supersedes them.

## Contract, mock and gold boundaries

| Evidence | Scope |
| --- | --- |
| [frontend-contract/browser-contract-report.json](frontend-contract/browser-contract-report.json) | 19 consumer-contract browser cases passed using HTTP interception. This is not real-backend product acceptance. |
| [frontend-mock/browser-mock-relations-report.json](frontend-mock/browser-mock-relations-report.json) | 5 explicitly labelled mock browser cases passed. This is not real-backend product acceptance. |
| [gold-source-checks.json](gold-source-checks.json), [gold-source-checks.log](gold-source-checks.log) | 10/10 gold source locations and hashes for 16 corpus files verified. `retrieval_evaluation=not_run` and `human_B_review=pending`. The corpus is the numbered placeholder corpus; this evidence does not establish retrieval quality or completed B-team review. |

## Retained failures and their closure

Historical failed attempts remain in this directory to preserve the audit trail.

| Retained attempt | Finding and final closure |
| --- | --- |
| [frontend-live-normal/README.md](frontend-live-normal/README.md) and its `browser-live-first-import-report.json` | Initial import reached 12 `basic_ready` files before keyword search could find content. Chunk/keyword-sidecar/relation persistence and `basic_ready` publication now share a transaction. The final `frontend-live-clean` first import, with `frontend-live-fresh` as additional evidence, passed after that repair. |
| [http-db-final-first-attempt.json](http-db-final-first-attempt.json) | The verifier incorrectly required exactly 12 historical completed embedding jobs. Legitimate recovery after model readiness created additional history. The verifier now checks current coverage and absence of duplicate live jobs, with three regression tests; `http-db-final.json` passed 202/0. |
| [w7-audit-container-tests.log](w7-audit-container-tests.log) | The first image run had 19 failures/720 passes: missing gold/freeze/historical-manifest assets and a runtime without Git. Packaging now includes the exact required JSON assets, and source-state reporting tolerates unavailable Git while retaining source hashes. Final image checks passed 744/0. |
| [w7-audit-migrations.log](w7-audit-migrations.log) | Initial downgrade failed because a keyword-sidecar foreign key still depended on `source_chunks`. Migration ordering was repaired; all five dedicated migration checks and the final Linux suite passed. |
| [retry-harness-first-attempt.json](retry-harness-first-attempt.json) | The temporary cache-lock test harness was configured incorrectly. After harness/cache repair, the real browser explicit-retry flow passed in `model-retry-browser.json`. |

## Reproduction

Run from the repository root against the separate verification stack. Set
`W7_DATABASE_URL` to its PostgreSQL database and expose the fixture mount
read-only. The HTTP verifier scans roots and appends synthetic review events; it
does not reset the database. A first-import reproduction needs a fresh database
or a never-imported directory, as indicated by the browser report.

```powershell
python scripts/verify_w7.py --base-url http://127.0.0.1:18081 --source-root tests/fixtures --out submissions/week07/evidence/20261031-w7/http-db-final.json
node scripts/verify_w7_browser.mjs --ui http://127.0.0.1:13002 --mount scenarios --directory normal12-fresh --expected-files 12 --expected-unsupported 0 --skip-relations --query invoices --output submissions/week07/evidence/20261031-w7/frontend-live-clean
node scripts/verify_w7_browser.mjs --ui http://127.0.0.1:13001 --mount corpus --directory . --expected-files 16 --expected-unsupported 4 --relations-mount relations --relations-directory . --query invoices --output submissions/week07/evidence/20261031-w7/frontend-live-mixed
python scripts/verify_model_startup.py --api-url http://127.0.0.1:18081 --ai-url http://127.0.0.1:18181 --source-root tests/fixtures --output submissions/week07/evidence/20261031-w7/model-ready.json
python scripts/validate_d_gold.py --report submissions/week07/evidence/20261031-w7/gold-source-checks.json
node scripts/validate_d_fixtures.mjs
```

Run backend Ruff and `python -m pytest tests/unit tests/integration -q` inside the
built image, with `SEARCH_TEST_DATABASE_URL` pointing to the isolated PostgreSQL
instance. Run `npm test -- --run`, `npm run test:integration` and `npm run build`
from `frontend`. The browser contract/mock scripts are supporting checks; their
interception/mock labels must be retained when recording results.

The local `verify_w7_scenarios.py`, `verify_w7_safety_pages.py`,
`verify_w7_model_modes.py` and `verify_w7_restart.py` capture this audit's extra
scenarios. Some bind this run's root IDs and environment; they are not general
acceptance CLIs. Model-mode verification requires external AI stop/start steps;
restart verification requires external container recreation. The scenario
recovery harness pauses the worker, processes one scan using the same image,
temporarily removes only the disposable work-copy file, resumes the worker and
then issues the HTTP retry. Original fixtures must stay unchanged. Read each
script's setup notes before reuse.
