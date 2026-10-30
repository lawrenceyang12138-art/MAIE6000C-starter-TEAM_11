# Operations Notes

Operating the W7 build: a read-only corpus, an API that accepts work, a worker
that does it, and a local AI service that can be absent without taking search
down. The starter's case-triage demo still runs, but the folder flow below is
the main path.

## 1. Prepare

1. `cp .env.example .env` and review `SOURCE_MOUNTS` (the allowlist the browser
   can choose from), `DATABASE_URL`, and the host port overrides.
2. Put the corpus where `compose.yaml` mounts it. The default mount points at
   `tests/fixtures` and is **demo data only** - a real corpus is mounted from
   wherever the operator keeps it, read-only.
3. Prepare the pinned local model under `models/pplx-embed-v2-late-0.6b` using
   `python -m scripts.search_tools download-model`, then initialize the C token
   index using `python -m scripts.search_tools prepare-token-index --database-url YOUR_URL`.
   This model uses 128-dimensional token vectors and MaxSim. Its weights and
   token index are described in `docs/search-team-pdf-evaluation.md`.
   Without it, keyword search still works and semantic results degrade visibly.

   The synthetic C chunk fixture uses an isolated, generated source tree:

   ```bash
   python -m scripts.search_tools seed --fixture-root work/search-fixtures
   python -m scripts.search_tools evaluate --fixture-root work/search-fixtures
   ```

   The API HTTP verifier sets `search-fixtures` to the same default root. For a
   separately started API, set `SOURCE_MOUNTS` to
   `{"search-fixtures":"<absolute fixture root>"}`. These generated text bytes
   are identity fixtures for hand-authored chunks, not parsed-PDF evidence.

## 2. Start, stop, reset

```bash
docker compose up -d --build     # api runs `alembic upgrade head` first
docker compose ps                # wait for api/ai healthy, db healthy
docker compose logs -f worker    # watch job processing
docker compose down              # stop, keep data (postgres_data volume)
docker compose down -v           # stop and DELETE the database volume
```

Host ports default to api `8000`, db `15432` (5432 sits in a Windows reserved
range), ai `18100`, frontend `3000` (bound to loopback only).

## 2b. Frontend mode

The UI is a static Vite build behind nginx; `/api` is proxied to the api
service, so the browser never needs a second origin. The mode is a **build
argument**, not a runtime switch:

```bash
# default: labelled simulation, safe for a bare `up`
docker compose up -d --build

# real stack
FRONTEND_DATA_MODE=api docker compose build frontend
FRONTEND_DATA_MODE=api docker compose up -d frontend
```

Every route the adapter calls is assembled (mounts, roots, rescans, jobs and
retry by A; files, evidence, relations by B), so `api` mode is a working path.
API failures surface as errors; they never fall back to mock data.

## 3. Health and capability

- `GET /health/live`, `GET /health/ready` - process and database readiness.
- `GET /metrics` - Prometheus counters and latency histograms.
- AI readiness is separate: `/health/ready` on the ai service. The API and
  worker do not require it, and search degrades to keyword mode without it.

## 4. The main path

```bash
curl -s localhost:8000/mounts
curl -s "localhost:8000/mounts/corpus/directories?relative_path=."
curl -s -X POST localhost:8000/roots \
  -H 'content-type: application/json' \
  -d '{"mount_id":"corpus","relative_path":"."}'
# -> {"root_id": "...", "job_id": 34, "status": "pending"}
```

Then follow progress with `GET /jobs/{job_id}`, and read the folder with
`GET /roots/{root_id}` (stage counts) and `GET /files?root_id=...` (one row per
file with its current version status). `POST /roots/{root_id}/scans` queues
another scan; it answers `409 active_job_exists` while one is still running.

## 5. Failures and retry

A damaged, encrypted or unsupported document is **not** a failed job. It is a
completed job whose version is marked `unsupported` with a reason code
(`corrupt`, `encrypted`, `no_text_layer`, `unsupported_format`), visible in
`GET /files`. Other files keep processing.

A file whose bytes could not be read is a different answer, and it is visible
too: `GET /files` reports `presence_status` (`missing` / `unavailable`) plus
`presence_reason` (`file_missing`, `unreadable`, `not_a_regular_file`). A file
that was readable last scan and is not readable now stops being `present`; its
`version_id` still points at the last content that was read. Only `missing` means
the file is gone - a directory the scan could not list, or refused to enter,
leaves its files `unavailable` / `unreadable` instead, and the worker log says so
(`directories_unreadable`, `directories_skipped`). One bad file never blocks the
others.

A version that could not be processed **this time** (`failed`: the file was
gone, changed while being read, or the store errored) fails its job as well. That
is what makes recovery possible:

```bash
# 1. the source is back with the same bytes; a rescan just marks it present
curl -s -X POST localhost:8000/roots/{root_id}/scans
# 2. retry the failed extraction explicitly
curl -s -X POST localhost:8000/jobs/{job_id}/retry
```

Only `failed` jobs are retryable, `attempts` is kept across retries, and a live
job on the same target is refused with `409 active_job_exists`. A scan is not an
implicit retry: a permanently broken file does not generate one new job per scan.

Inspect with `GET /jobs/{job_id}`: `status` plus `error_code` (the handler's
reason, e.g. `file_missing`, or `job_failed` when there is no recorded reason).
Diagnostic text stays in the database and is never returned.

## 6. Persistence check

```bash
docker compose restart db api worker
# or: docker compose down && docker compose up -d   (no -v: keeps the volume)
curl -s localhost:8000/roots
```

The same roots, the same stage counts and the same jobs must come back. If they
do not, check `docker volume ls | grep postgres_data` before assuming data was
lost. `down -v` deleting the database is expected, not a bug.

## 7. Common problems

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `404 unknown_mount` on `POST /roots` | mount id not in `SOURCE_MOUNTS` | add it to `.env` and restart api |
| `403 path_out_of_scope` | absolute path, `..`, or a symlink/junction resolving outside the mount | send a relative path inside the mount |
| `404 source_unavailable` on `POST /roots` | the path is not a directory inside the mount | check `GET /mounts/{id}/directories` |
| `409 active_job_exists` | a scan for that folder is still running | wait, or watch the existing `job_id` |
| file stuck at `discovered` | worker not running or cannot read the mount | `docker compose logs worker` |
| file `present` but no text | content is unreadable or unsupported | check `presence_reason` and `error_code` in `GET /files` |
| semantic results missing | no embedding model on disk | keyword search remains; see `degraded` in `POST /search` |
| api unhealthy after start | migration failed | `docker compose logs api` for the alembic error |

## 8. Tests

```bash
pytest tests/unit tests/integration -q     # no stack needed
ruff check .
SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q   # needs the stack
```

Smoke tests and the postgres-marked tests are skipped without a stack; report
the skip reason rather than counting them as passes.

## 9. Evidence

`scripts/w7_evidence_probe.py` runs the scan path against a live stack and
writes JSON plus a Markdown summary: first scan, repeat scan, originals' hash
before and after. Use it to regenerate `submissions/week07/evidence/` after any
change to scanning.
