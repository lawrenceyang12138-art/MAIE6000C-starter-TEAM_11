# Team 11 File Trace frontend

The React/Vite frontend uses the real local API by default. Its W7 workflow is:
choose an allowlisted read-only directory, authorize and scan, inspect persisted
file progress, search current PDF text, open the matched source passage, and
confirm/correct/reject evidence-backed relation candidates. It never switches
to mock data after an API failure.

## Run with the integrated application

From the repository root, with Python and Docker Desktop/Compose installed:

```powershell
python scripts/start.py
```

Open [File Trace](http://127.0.0.1:3000/select). The launcher preserves existing
`.env` settings. Compose defaults to `FRONTEND_DATA_MODE=api`; an existing
explicit `mock` setting still selects a labelled simulation. The frontend
shows real local-model preparation status and supports retry without blocking
keyword search. Model readiness does not imply every document already has vectors.

Nginx serves the production build and proxies `/api` to the API service. Direct
refreshes on `/select`, `/scan/:jobId`, `/results/:rootId`, `/graph` and `/review`
resolve to the SPA. `/health` checks static serving only.

## Run locally with Node

```powershell
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000`. API and
Worker must run separately for a live workflow. To use a different local API,
set `VITE_API_BASE_URL` before starting Vite, or configure its same-origin proxy.
No browser fixture represents live API, database or Worker acceptance.

## Source and review behavior

Content search calls `POST /search`, scoped to the selected root, and defaults
to keyword mode. Semantic/hybrid modes remain explicit choices; requested mode,
effective mode and any degradation are shown. A separate catalog filter only
filters loaded file records.

Search hits open `GET /evidence/{chunk_id}` and validate chunk, file, version,
page, ordinal and path. Source refusal codes hide cached text, including when
source bytes changed before a rescan.

Relations and review read `GET /versions/{version_id}/relations`. Each relation
opens its returned `chunk_id` directly, then verifies file, version, page, path
and the full quote before enabling review. No keyword search is needed to locate
a relation, so multiple chunks on one page cannot select another passage.
Missing evidence keeps both the quote and review unavailable.

Reviews send `expected_revision`, reviewer, reason and a decision. Corrections
offer a dropdown of the current document's existing candidate entities,
excluding the current target; another known existing entity ID can also be
entered. Success requires a receipt matching
the relationship, decision and next revision. Double submissions are blocked;
conflicts and uncertain writes require a fresh server read before another POST.
Original files remain read-only.

## Explicit mock demonstrations

For an isolated synthetic sample with one fictional document and three candidates:

```powershell
$env:VITE_DATA_MODE = "mock"
$env:VITE_MOCK_SCENARIO = "relations"
npm run dev
```

Choose the synthetic mount and `sample` directory on `/select`. The sample
supports source verification and confirm/correct/reject; a correction can use
`entity-replacement`. Decisions last until a full reload. It contains no real
PDF/parser/model output and carries a persistent simulation notice.

Use `VITE_MOCK_SCENARIO=files` for the historical frozen 16-file demo. Set
`VITE_DATA_MODE=api` (or remove the override) to return to live services. API mode
ignores mock scenarios.

## Verification

```powershell
npm run fixtures:check
npm run test:mock
npm run test:integration
npm run gold:check
npm test -- --run
npm run build
```

The 31 October W7 verification passed 56 Vitest tests, 56 Node HTTP contract
checks, mock/fixture checks and the production build. React regressions cover
direct relation source lookup, mismatched locators, missing chunks and review
locking. Contract tests inject HTTP responses; they do not substitute for a
live integration run. Historical reports remain under
`../submissions/week07/evidence/1016-D/` and `1019-D/`.

Browser scripts launch a separate headless Chromium profile using pinned
`playwright-core`; they never attach to an existing browser session. Set
`D_BROWSER_EXECUTABLE` to another installed Chromium executable if needed.
With an API-mode Vite server running:

```powershell
$env:D_UI_URL = "http://127.0.0.1:5173"
$env:D_UI_OUTPUT = "submissions/week07/evidence/20261031-w7/frontend-contract"
npm run test:browser:contract
```

The 31 October contract run passed 19 scenarios, including search/evidence,
source loss and recovery, all review decisions, conflict reload, rescan, failed
job retry, and 375/768/1024/1440 viewport checks, with zero page runtime errors.
Its screenshots carry an explicit fixture watermark. `test:browser:mock`
requires the separate explicit `relations` mock server and performs no HTTP
interception. `D_UI_OUTPUT` prevents either script from overwriting historical
reports. See the W7 acceptance evidence for live-service results.

For the real W7 stack with the synthetic `corpus` and `relations` mounts:

```powershell
npm run test:browser:live -- --ui http://127.0.0.1:3000 --query invoices --output work/w7-browser
```

This live verifier authorizes through the UI, waits for the Worker, searches and
opens source evidence, rescans without duplicate file/version identities, and
records all three review decisions using real entity choices. It checks saved
decisions after a reload and records screenshots and API responses. It performs
no HTTP interception. Override the mount/directory and expected counts with the
options shown by `npm run test:browser:live -- --help`; its default corpus expects
12 normal PDFs and four explicitly unsupported inputs. The named review actor
identifies an automated fixture check and does not stand for a team member's
manual acceptance or academic judgment.
