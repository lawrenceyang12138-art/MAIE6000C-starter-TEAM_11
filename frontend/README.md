# Team 11 D demo frontend

This is the React/Vite role-D frontend. The 16 October update defaults to the real HTTP adapter and preserves explicit Mock mode for demonstrations. A/B/C-owned Python models, migrations, worker, and public API are unchanged. **The inspected backend still lacks the file-management routes: API mode will show a real error until A provides them.** See `../submissions/week07/ui-progress.md` for delivered work and incomplete acceptance items.

## Run with Docker Compose (recommended)

From the repository root:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build frontend
```

Open `http://localhost:3000/select`. The frontend is built as a static Nginx
image, uses API mode by default, and exposes `/health` for the Compose
healthcheck. The `/scan/:jobId` and `/results/:rootId` routes also work on a
direct refresh because the Nginx config falls back to `index.html`.
The frontend health endpoint checks static serving only, not backend or model readiness.
The healthcheck uses `127.0.0.1` explicitly because Nginx listens on IPv4 and Alpine may resolve `localhost` to `::1`. This source fix has not been deployed to the existing container; the 16 October verification only inspected Docker read-only.

API mode uses these settings in `.env` before rebuilding (do not overwrite an existing `.env` just to select a mode):

```dotenv
FRONTEND_DATA_MODE=api
FRONTEND_API_BASE_URL=/api
```

The `/api` path is reverse-proxied by Nginx to the Compose `api` service. The
current starter API does not expose the file-management routes yet, so this
mode displays service errors until the corresponding backend work lands. It never silently switches to Mock. For explicit simulated demonstrations set `FRONTEND_DATA_MODE=mock` and rebuild; a persistent simulation notice is shown.

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

The adapter maps to mounts/directories, `POST /roots`, Job reads, independent `GET /roots/{root_id}` file counters, file lists, and version-bound evidence. The D consumer contract is documented in `../docs/frontend-integration-contract.md`; it still needs A's confirmation. The results box filters loaded records, not a `POST /search` semantic endpoint.

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

The fixture validator checks 16 synthetic files, 20 normal PDF pages, SHA-256 values, and the 12/3/1 category split. Mock tests cover the 202 contract, progress polling, empty and invalid directories, deduplication, and version-bound evidence.

`test:integration` uses Node's built-in test runner with injected HTTP responses; it is not a live API integration test. `gold:check` needs `pypdf` and checks actual PDF source locations and frozen hashes, not retrieval scores. The frozen queries are source-location smoke tests over numbered placeholder text and await B review.

## Browser contract evidence

Build in API mode and start `npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`, then set `D_UI_URL=http://127.0.0.1:4173` in the capture process and run `node scripts/capture_d_ui.mjs` from the repository root. The script also accepts a local API-mode Vite dev server (default port 5173). It needs an already installed Playwright module; set `D_PLAYWRIGHT_MODULE` to its absolute module path if it is not available in `frontend/node_modules`. Set `D_BROWSER_EXECUTABLE` only when using an already installed compatible test browser. This launches a separate headless session, not the user's open browser profile.

The script intercepts `/api` with contract fixtures and captures authorization, progress, empty, parse-failed, source-unavailable, keyword-only, unknown-count and API-error states. All **8 scenarios passed** against the production build on 16 October; page runtime errors were zero. All 8 screenshots have been visually inspected and are watermarked **NOT PRODUCT EVIDENCE**. See `../submissions/week07/evidence/1016-D/README.md`. Real service screenshots and live integration are still required separately; simulated screenshots do not close that acceptance item. Do not use this request-intercepting script for real acceptance.
