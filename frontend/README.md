# Team 11 D demo frontend

This is the React/Vite role-D frontend, updated through 19 October. The adapter defaults to the real HTTP client, while the shipped Compose demo builds in explicit Mock mode because the backend routes it needs are not assembled yet. Mock stays an explicit build choice and is never a failure fallback. A/B/C-owned Python models, migrations, worker, and public API are unchanged. **The inspected backend still lacks the assembled file-management, evidence and review routes: API mode shows real errors until those services are provided.** See `../submissions/week07/ui-progress.md` for delivered work and incomplete acceptance items.

## Run with Docker Compose (recommended)

From the repository root:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build frontend
```

Open `http://localhost:3000/select`. The frontend is built as a static Nginx
image, defaults to `FRONTEND_DATA_MODE=mock` (a persistent simulation banner is
shown), and exposes `/health` for the Compose healthcheck. The `/scan/:jobId`,
`/results/:rootId`, `/graph` and `/review` routes also work on a direct refresh
because the Nginx config falls back to `index.html`.
The frontend health endpoint checks static serving only, not backend or model readiness.
The healthcheck uses `127.0.0.1` explicitly because Nginx listens on IPv4 and Alpine may resolve `localhost` to `::1`. This source fix has not been deployed to the existing container; the 16 October verification only inspected Docker read-only.

Compose passes `FRONTEND_DATA_MODE` into `VITE_DATA_MODE` at build time. Copy
`.env.example` to `.env` before rebuilding (do not overwrite an existing `.env`
just to select a mode):

```dotenv
FRONTEND_DATA_MODE=mock   # default: explicit simulation, never a fallback
FRONTEND_API_BASE_URL=/api
```

The `/api` path is reverse-proxied by Nginx to the Compose `api` service. Switch
to `FRONTEND_DATA_MODE=api` only after A/B assemble the mount, file, evidence and
relation routes; that mode displays real service errors and never silently
switches to Mock. A bare `docker build` of `frontend/` still defaults to `api`
because the Dockerfile keeps `VITE_DATA_MODE=api`; Compose overrides it.

## Run locally with Node

```powershell
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

API mode requires A's file-management service. For an explicitly simulated demonstration, set `$env:VITE_DATA_MODE = "mock"` before starting Vite, open its printed URL and use this fixture-only flow:

1. `/select` - choose the synthetic read-only mount and a relative directory.
2. `/scan/job-scan-demo-01` - observe `pending -> running -> completed` and the `12 / 3 / 1` counters.
3. `/results/root-demo-01` - expand a normal file to inspect page evidence; failed and unsupported files keep their visible reason.

The adapter defaults to same-origin `/api`, proxied by Vite to `http://127.0.0.1:8000`. To select a different local API explicitly:

```powershell
$env:VITE_DATA_MODE = "api"
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

Prefer the same-origin proxy to avoid cross-origin configuration. To run the old JSON demonstration deliberately, set `$env:VITE_DATA_MODE = "mock"` before `npm run dev`; clear it or select `api` to return to real service reads.

The content search form calls canonical `POST /search`, scoped to the selected root. It defaults to keyword; hybrid/semantic modes are explicit choices. Requested/effective mode and degradation are displayed separately. Search results open canonical `GET /evidence/{chunk_id}` and validate file, version, page, ordinal and path. A separate catalog input only filters loaded records.

`/graph` lists up to 20 relations for a selected current version. `/review` offers confirm/correct/reject after source verification. A correction needs an existing entity ID. The UI sends `expected_revision`, blocks duplicate submissions, and requires a fresh read after conflict or uncertain write acceptance. See `../docs/frontend-integration-contract.md` for the source-quote lookup limitation and provisional review receipt shape. Empty relations and unavailable endpoints remain separate states. Explicit Mock mode simulates keyword search only. The default `files` scenario preserves the frozen 16-file fixture and returns no relation candidates.

To operate the new relation/review screens without an assembled backend, start the separate synthetic contract sample:

```powershell
cd frontend
$env:VITE_DATA_MODE = "mock"
$env:VITE_MOCK_SCENARIO = "relations"
npm run dev
```

Open `/select`, choose the synthetic relation mount and the `sample` directory, then authorize. Open Graph to see three person/project/topic candidates, or Human Review to verify each source passage and confirm/correct/reject. Enter a reviewer name; a correction can use the existing sample ID `entity-replacement`. Decisions remain in memory while navigating and reset on a full page reload. This sample contains one fictional document and no real PDF/parser/model output; it does not modify the frozen 16-file corpus. Select `VITE_MOCK_SCENARIO=files` to restore the original demonstration, or `VITE_DATA_MODE=api` to use HTTP services. API mode ignores the Mock scenario.

## Checks

```powershell
npm run fixtures:check
npm run test:mock
npm run test:integration
npm run gold:check
npm test -- --run
npm run build
```

The package pins direct dependency versions and now includes a registry-generated
`package-lock.json`; keep it with the source for reproducible `npm ci` installs.
The dependency installation, API-mode production build and 9 Vitest tests passed
on 16 October. The Vitest tests cover adapters/helpers, not React components.

The latest 19 October verification passes 55 Node contract tests and 21 Vitest tests,
including eleven React workflow tests, the API-mode production build, Mock regression,
fixture validation and frozen gold source-location checks. If Windows checkout
has changed frozen fixture bytes to CRLF, run `node scripts/restore_d_fixture_checkout.mjs`
from the repository root before the fixture/gold checks. The script refuses actual
content changes and restores only bytes that match both HEAD and the frozen hashes.
Candidate quotes are labelled unverified before source inspection. Failed source
reads hide the stored quote and keep review disabled. The latest browser report
verifies this guard and recovery against the current source hashes.

The fixture validator checks 16 synthetic files, 20 normal PDF pages, SHA-256 values, and the 12/3/1 category split. Mock tests cover the 202 contract, progress polling, empty and invalid directories, deduplication, and version-bound evidence.

`test:integration` uses Node's built-in test runner with injected HTTP responses; it is not a live API integration test. `gold:check` needs `pypdf` and checks actual PDF source locations and frozen hashes, not retrieval scores. The frozen queries are source-location smoke tests over numbered placeholder text and await B review.

## Browser contract evidence

`npm ci --ignore-scripts` installs the pinned `playwright-core` test dependency;
it does not download a browser. The capture scripts use an installed Chrome in
a separate headless profile. To use another installed Chromium browser, set
`D_BROWSER_EXECUTABLE` to its executable. `D_PLAYWRIGHT_MODULE` remains an optional
override for an existing Playwright-compatible module.

Build in API mode, start `npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`,
then run this from `frontend/` in another terminal:

```powershell
$env:D_UI_URL = "http://127.0.0.1:4173"
npm run test:browser:contract
```

The script also accepts a local API-mode Vite dev server (default port 5173).

The current 19 October report records 19 passed cases with zero page errors: search/evidence,
empty/error/fallback states, source invalidation, three review decisions, revision conflicts,
missing endpoints, rescan, failed-Job retry, source-read failure and recovery, and
1440/1024/768/375 viewport checks. The report
and existing watermarked screenshots live in `../submissions/week07/evidence/1019-D/`. HTTP
is intercepted with fixed contract samples: `product_acceptance` is false. Real
database/Worker/API acceptance is still required.
`npm run test:browser:mock` additionally exercises the explicit `relations` sample
without HTTP interception. Start the sample using the local run instructions
above, then set `D_UI_URL` to that Mock server before running this command from
`frontend/`. Its five cases passed with no runtime errors or API requests; the
separate report records directory authorization, search, source verification and
all three decisions. It is also not product acceptance.
The older script `capture_d_ui.mjs` now saves rechecks under `work/d-legacy-contract-recheck/`
so the original 16 October evidence is preserved. Its eight legacy cases also pass.

The script intercepts `/api` with contract fixtures and captures authorization, progress, empty, parse-failed, source-unavailable, keyword-only, unknown-count and API-error states. All **8 scenarios passed** against the production build on 16 October; page runtime errors were zero. All 8 screenshots have been visually inspected and are watermarked **NOT PRODUCT EVIDENCE**. See `../submissions/week07/evidence/1016-D/README.md`. Real service screenshots and live integration are still required separately; simulated screenshots do not close that acceptance item. Do not use this request-intercepting script for real acceptance.
