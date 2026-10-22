# Starter Architecture

## Components

- **API service**: accepts requests, validates input, persists workflow state
- **PostgreSQL**: stores cases and jobs
- **Worker**: polls pending jobs and processes them outside the request cycle
- **AI service**: receives internal triage requests and returns a label, summary, and confidence

## Baseline flow

1. client sends `POST /cases`
2. API writes a case row
3. API writes a pending job row
4. worker claims the pending job
5. worker calls the internal AI service
6. worker writes the triage result back to the case
7. API exposes the updated case state

## Why this starter exists

This starter is intentionally small.

Its purpose is to demonstrate the engineering shape of the course contract:

- persistence
- API boundaries
- async work
- service-to-service communication
- testing
- observability
- reproducible deployment

## Current limitations

- single polling worker
- simple heuristic AI service placeholder
- no authentication or authorization
- no retry strategy beyond basic failure recording
- minimal domain model

---

## As implemented (W7)

This section records what actually runs today. The Week 4 architecture proposal
in `origin/week04-architecture-proposal` remains the design authority for scope
and for deferred capabilities; where the two differ, this section describes the
current build, not the target.

### Components

| Component | Runs as | Reads / writes |
| --- | --- | --- |
| `frontend` | static Vite build behind nginx, port 3000 (loopback) | calls only the API through the same-origin `/api` proxy |
| `api` | FastAPI, port 8000 | PostgreSQL; source files read-only for preview |
| `worker` | polling process, no HTTP | claims jobs, reads source files, writes versions and chunks |
| `ai` | FastAPI, port 8100 | embeddings and triage only; no database, no filesystem |
| `db` | PostgreSQL 16 + pgvector | all durable state |

### Folder flow

1. `GET /mounts` lists the allowlisted read-only mounts; the browser picks a
   `mount_id` plus a relative path.
2. `POST /roots` validates the path inside the mount, stores the authorized
   root and one `scan_root` job in the same transaction, returns `202` with
   `root_id`, `job_id` and `pending`.
3. The worker walks the folder, hashes each file, and reuses or creates one
   `file_versions` row per distinct content; it moves
   `files.current_version_id` and queues `extract_file` in the scan
   transaction.
4. Extraction stores chunks and marks the version `basic_ready` (or
   `unsupported`/`failed` with a reason); only then is one `embed_file` job
   queued.
5. `GET /roots/{root_id}` reports stage counts of the *current* versions;
   `GET /files?root_id=` lists one row per file.
6. `POST /roots/{root_id}/scans` rescans; `POST /jobs/{job_id}/retry` requeues
   a failed job. Both refuse when work is already live for the same target.

### State vocabulary as served

Version: `discovered` -> `extracting` -> `basic_ready` -> `enriched`, with
`failed` and `unsupported` as recorded outcomes that carry a reason code.
Job: stored as `pending` / `claimed` / `completed` / `failed`, but `claimed` is
served as `running` so the client sees one vocabulary.

### Known limits of this build

- manual scans only, no filesystem watcher;
- one worker; no claim token, lease, `FOR UPDATE SKIP LOCKED` claim or automatic
  backoff, so multi-worker safety and crash recovery are not claimed;
- route-level tests use SQLite; PostgreSQL is exercised by the compose smoke
  path and the evidence runs in `submissions/week07/evidence/`;
- symlink-escape rejection is implemented but not yet verified on a host that
  can create symlinks.
