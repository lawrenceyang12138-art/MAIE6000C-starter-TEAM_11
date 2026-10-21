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
3. Optional: place the embedding model under `models/multilingual-e5-small`.
   Without it, keyword search still works and semantic results degrade visibly.

## 2. Start, stop, reset

```bash
docker compose up -d --build     # api runs `alembic upgrade head` first
docker compose ps                # wait for api/ai healthy, db healthy
docker compose logs -f worker    # watch job processing
docker compose down              # stop, keep data (postgres_data volume)
docker compose down -v           # stop and DELETE the database volume
```

Host ports default to api `8000`, db `15432` (5432 sits in a Windows reserved
range), ai `18100`.

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

Only infrastructure errors fail a job. Inspect with `GET /jobs/{job_id}`
(`error_code`) and requeue with `POST /jobs/{job_id}/retry`; only `failed` jobs
are accepted, and a live job on the same target is refused with `409`.

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
| `403 path_out_of_scope` | absolute path or `..` in `relative_path` | send a relative path inside the mount |
| `409 active_job_exists` | a scan for that folder is still running | wait, or watch the existing `job_id` |
| file stuck at `discovered` | worker not running or cannot read the mount | `docker compose logs worker` |
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
