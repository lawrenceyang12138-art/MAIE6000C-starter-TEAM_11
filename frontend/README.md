# Team 11 D demo frontend

This is the React/Vite mock-first slice for the 10/14-10/15 role-D tasks. It deliberately stays separate from the starter Python services so the A/B/C-owned models, migrations, worker, and public API are unchanged.

## Run with Docker Compose (recommended)

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build frontend
```

Open `http://localhost:3000/select`. The frontend is built as a static Nginx
image, uses Mock mode by default, and exposes `/health` for the Compose
healthcheck. The `/scan/:jobId` and `/results/:rootId` routes also work on a
direct refresh because the Nginx config falls back to `index.html`.
Mock mode does not wait for the Python API or database to become healthy.

To build the same image against the future API adapter, set these values in
`.env` before rebuilding:

```dotenv
FRONTEND_DATA_MODE=api
FRONTEND_API_BASE_URL=/api
```

The `/api` path is reverse-proxied by Nginx to the Compose `api` service. The
current starter API does not expose the file-management routes yet, so this
mode is a contract check and will return the API's normal `404` responses until
the corresponding backend work lands.

## Run locally with Node

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite and use this flow:

1. `/select` - choose the synthetic read-only mount and a relative directory.
2. `/scan/job-scan-demo-01` - observe `pending -> running -> completed` and the `12 / 3 / 1` counters.
3. `/results/root-demo-01` - expand a normal file to inspect page evidence; failed and unsupported files keep their visible reason.

The adapter defaults to local JSON in `src/mock/data.json`. To point the same UI at the future API contract:

```powershell
$env:VITE_DATA_MODE = "api"
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

When using Vite directly, use an absolute API URL such as
`http://localhost:8000`; the `/api` reverse proxy exists only in the Docker
image.

The API adapter maps to `GET /mounts`, `GET /mounts/{mount_id}/directories`, `POST /roots`, `GET /jobs/{job_id}`, `GET /files`, and the file evidence read. The current starter API does not expose those routes yet, so API mode is intentionally opt-in.

## Checks

```powershell
npm run fixtures:check
npm test -- --run
npm run build
```

The package currently pins direct dependency versions. A complete
`package-lock.json` should be generated and committed when this environment can
reach the npm registry; the Dockerfile accepts it with `npm ci` and currently
falls back to `npm install` when it is absent.

The fixture validator checks 16 synthetic files, 20 normal PDF pages, SHA-256 values, and the 12/3/1 category split. Mock tests cover the 202 contract, progress polling, empty and invalid directories, deduplication, and version-bound evidence.
