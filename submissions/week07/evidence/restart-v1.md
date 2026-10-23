# Restart persistence

Date: 2026-10-21 (Asia/Hong_Kong)
Code: commit `64ad2ed` (branch `Role_A`)
Environment: Docker Compose on Windows 11; PostgreSQL 16 + pgvector in the
`db` container, persistent `postgres_data` volume.

## What was restarted

First pass, in place:

```bash
docker compose restart db api worker
```

The `api` service runs `alembic upgrade head` before starting uvicorn, so this
also proves the migration is idempotent on a database that already has content:
the container came back healthy instead of failing on an existing revision.

The `ai` container was deliberately left running; it holds no product state.

## Observed before and after

Root `bec3ef8d-8803-4b87-bd23-738ca36c354c` (mount `corpus`, path `regression`),
created before the restart.

| Measure | Before restart | After restart |
| --- | --- | --- |
| root id returned by `POST /roots` | `bec3ef8d-...-738ca36c354c` | same id (existing root reused, no new authorization) |
| files reported by `GET /files` | 13 | 13 |
| `file_counts` | total 13, `basic_ready` 12, `unsupported` 1 | identical |
| presence | 13 `present` | 13 `present` |
| new file rows created by the post-restart scan | - | 0 |
| version/job duplication | `scan_root 2`, `extract_file 13`, `embed_file 12` | scan jobs continued at 61/62, totals unchanged |
| original files' SHA-256 | 18 checked, 0 changed | 18 checked, 0 changed |

The post-restart scan produced job 61 and its rescan job 62, so the identifier
sequence continued rather than restarting from 1 - the job table survived with
its data, and the queue was empty at rest (no `pending` or `claimed` leftovers
were resurrected or duplicated).

## Commands actually run

```bash
docker compose restart db api worker
docker compose ps                # api and worker healthy again
python scripts/w7_evidence_probe.py --path regression \
  --out submissions/week07/evidence/restart-after.json
```

After the restart the probe found the same root, the same 13 files and the same
stage counts; the JSON above is that run.

## Second pass: containers recreated

```bash
docker compose down          # no -v: the postgres_data volume is kept
docker compose up -d
```

All four containers and the network were removed and recreated; the API
re-ran `alembic upgrade head` against the **already populated** database and
came back healthy, so the migration chain is idempotent on real data, not only
on an empty database.

| Measure | Value after recreation |
| --- | --- |
| root id returned by `POST /roots` | `bec3ef8d-...-738ca36c354c` (unchanged) |
| files reported by `GET /files` | 13 |
| `file_counts` | total 13, `basic_ready` 12, `unsupported` 1 |
| new file rows created by the scan | 0 |
| job ids used | 63 (scan), 64 (rescan) - the sequence continued |
| original files' SHA-256 | 18 checked, 0 changed |

Direct database counts, taken outside the API:

```text
roots    |  2
files    | 29
versions | 29
jobs     | 64
```

Reading across both roots: 16 + 13 = 29 files, and 29 `file_versions` - one
version per file after every scan in this document (11 scans in total across
the two roots). `jobs` at 64 with the highest id at 64 means the identifier
sequence has no gaps: no job row was created and rolled back.

## Limits, stated plainly

- Both passes keep the `postgres_data` volume. Nothing here claims that data
  survives `docker compose down -v`, and it should not: that deletes the volume
  on purpose.
- Only PostgreSQL persistence is covered. Worker crash recovery, lease expiry
  and retry-after-crash are outside W7 and not claimed.
