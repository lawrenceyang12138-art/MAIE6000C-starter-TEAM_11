# W7 acceptance summary — 2026-10-31

This is a concise historical summary of the isolated API/Worker/PostgreSQL/AI
and browser verification of `feat/c-team-pdf-evaluation`. It is not a new test
run. The audit used baseline `0e3d715` plus then-uncommitted fixes, which were
subsequently committed by topic. The recorded results apply to that snapshot.

Only this summary and [the aggregate result](final-validation.json) are retained
in Git. Raw HTTP/DB snapshots, browser response timelines, machine paths,
logs/XML/TAP output, screenshots and run-specific Python/Compose helpers remain
in the local ignored archive under `work/pr-evidence-backup/`. They are not
runtime inputs or required project source. Reusable verifiers remain in
`scripts/`. The archive is not delivered by cloning this repository.

## Results

| Check | Historical result |
| --- | --- |
| Shared-contract acceptance matrix | 18/18 automated gates passed |
| Real HTTP/API/Worker/PostgreSQL workflow | 202 checks, 0 failures |
| Request/source safety and physical pages | 102 checks, 0 failures; 30/30 chunks verified |
| Empty-database browser first import/search/source/rescan | 3/3 scenarios passed with AI disabled |
| Mixed normal/abnormal input and relation review browser | 6/6 scenarios passed, including confirm/correct/reject and refresh persistence |
| Corpus processing | 16 files/versions, 30 chunks; 12 ready, 4 unsupported with explicit reasons |
| Native local-model semantic/hybrid and disconnection/restoration | Passed; verified existing model cache reused, no fresh download in this run |
| Setup failure/retry and missing-vector recovery | Passed |
| Normal DB/API/Worker/frontend recreation | Persistent data and reviews retained; 12 table digests matched |
| Source integrity | 17 original fixture files retained their hashes/sizes; mounts read-only |
| Final rebuilt Linux/Python/PostgreSQL suite | 744 passed, 0 skipped; Ruff clean |
| Frontend snapshot | 56 Vitest and 56 Node tests passed; production build passed |
| Later Node follow-up at `2b975a0` | 62/62 passed, 0 skipped; did not rerun the full stack |
| Browser HTTP fixtures / explicit mock | 19 contract and 5 mock scenarios passed; not real-backend acceptance |
| Frozen source checks | 10/10 locations and 16/16 hashes; not a retrieval-quality measurement |

Earlier Windows runs skipped symlink privilege and FIFO cases; both were
executed in the final Linux run. A second fresh-directory browser run confirmed
first-import behavior. These overlapping runs are not added together.

## Findings and repairs

- First-import readiness initially preceded keyword persistence. Text,
  keyword-sidecar/relation writes and `basic_ready` publication now share a
  transaction; final first-import checks passed.
- A verifier incorrectly required exactly twelve historical embedding jobs.
  It now checks current coverage and duplicate live work; the repaired run
  passed all 202 HTTP/DB checks.
- The first image lacked frozen evaluation assets and assumed Git availability.
  Packaging and runtime source-state reporting were repaired; final image
  tests passed.
- Migration downgrade initially removed canonical tables before dependent
  search sidecars. Ordering was repaired and migration checks passed.
- A temporary cache-lock retry harness was misconfigured. After repair, the
  real browser's explicit retry flow passed.

The summary preserves these failed-attempt findings without publishing their
raw response bodies, local environment details or temporary helpers.

## Reproduction

Use a separate disposable Compose project/database with synthetic fixtures
mounted read-only. Set `W7_DATABASE_URL` to that database and run from the repo
root. The HTTP verifier appends synthetic roots/reviews; it does not reset a
database. A first-import run needs an empty database or a new fixture directory.
Use the actual loopback URLs/mount IDs for the test deployment.

```powershell
python scripts/verify_w7.py --base-url http://127.0.0.1:18081 --source-root tests/fixtures --out work/w7-http-db.json
node scripts/verify_w7_browser.mjs --ui http://127.0.0.1:13002 --mount scenarios --directory normal12-fresh --expected-files 12 --expected-unsupported 0 --skip-relations --query invoices --output work/w7-browser-clean
python scripts/verify_model_startup.py --api-url http://127.0.0.1:18081 --ai-url http://127.0.0.1:18181 --source-root tests/fixtures --output work/w7-model-ready.json
python scripts/validate_d_gold.py --report work/w7-gold-source-checks.json
node scripts/validate_d_fixtures.mjs
```

Run Ruff and `python -m pytest tests/unit tests/integration -q` in the built
image with `SEARCH_TEST_DATABASE_URL` pointing to the isolated PostgreSQL.
Run `npm test -- --run`, `npm run test:integration` and `npm run build` in
`frontend`. The general verifiers cover the documented flows; reproducing
external AI stop/start, container recreation and source-copy interruption
requires the corresponding isolated setup and operator steps.

## Boundaries

The corpus is the checked-in synthetic fixture set. Original fixture bytes
and frozen answers remain unchanged. These results do not establish retrieval
quality, completed B-team gold review, human A/B/C/D sign-off, OCR, filesystem
watching or recovery of jobs interrupted by an abrupt Worker crash.
See [the acceptance matrix](../../../../docs/w7-acceptance.md) for scope and
[the shared contract](../../../../docs/team11-w7-shared-contract.md).
