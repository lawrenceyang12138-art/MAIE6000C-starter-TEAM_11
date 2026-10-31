# SourceLens architecture

## Historical starter baseline

The following baseline describes the original course starter before the W7
integration. Its limitations are historical; the current implementation is
recorded in the W7 section below.

### Baseline components

- **API service**: accepts requests, validates input, persists workflow state
- **PostgreSQL**: stores cases and jobs
- **Worker**: polls pending jobs and processes them outside the request cycle
- **AI service**: receives internal triage requests and returns a label, summary, and confidence

### Baseline flow

1. client sends `POST /cases`
2. API writes a case row
3. API writes a pending job row
4. worker claims the pending job
5. worker calls the internal AI service
6. worker writes the triage result back to the case
7. API exposes the updated case state

### Why this starter exists

This starter is intentionally small.

Its purpose is to demonstrate the engineering shape of the course contract:

- persistence
- API boundaries
- async work
- service-to-service communication
- testing
- observability
- reproducible deployment

### Historical baseline limitations

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
| `api` | FastAPI, port 8000 (loopback) | PostgreSQL; authorized source files read-only for evidence and previews; proxies local AI setup and query embedding requests |
| `worker` | polling process, no HTTP | claims jobs, reads the same authorized sources read-only, writes versions, chunks, keyword indexes, relation candidates and token embeddings |
| `ai` | FastAPI, port 8100 (loopback) | local embeddings and retained starter triage route; writable model cache only, no source mounts and no database connection |
| `db` | PostgreSQL 16 + pgvector | all durable state |

The canonical `files`, `file_versions` and `source_chunks` tables own source
identity and text. Search-derived fields live in `chunk_search_index`, token
matrices in `chunk_token_search_index`, and physical page metadata in
`version_page_search_metadata`; these do not duplicate the source model.

### Startup and local AI boundary

`python scripts/start.py` builds the dependency environments and starts Compose.
Only AI receives the writable `./models:/models` mount. Its cache contains
`perplexity-ai/pplx-embed-v2-late-0.6b` at the fixed revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`; preparation verifies pinned sizes and
SHA-256 hashes before loading and warming up local query/document inference.
Inference uses verified local files. Downloading public model files does not
send user queries or document contents to the model host, and no hosted inference
fallback is configured. AI receives text through internal embedding requests;
it does not resolve authorized source paths itself.

API startup depends on database health. Worker startup depends on database and
API health. Neither waits for AI readiness, so source parsing, keyword search,
evidence and review remain available while AI prepares, fails, is disabled or is
unreachable. Disabling embeddings also prevents Worker from sending document
text to AI. Semantic/hybrid requests report explicit degradation when their
required model or compatible document vectors are unavailable.

`GET /setup` and `POST /setup/retry` expose preparation status and retry through
the API. AI `/health/live` describes process liveness; `/health/ready` returns
503 until verified loading and warmup complete. API readiness checks its database
independently. Model readiness does not claim that every document has vectors:
Worker queues ordinary embedding jobs for eligible current parsed versions when
the model becomes ready, preserving keyword indexes throughout. See
[model startup operations](model-startup.md).

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
4. Successful extraction publishes source chunks, their keyword sidecars,
   rule-based relation candidates and evidence, and `basic_ready` in the same
   transaction. Thus a ready file is already keyword-searchable before any
   optional embedding job runs. Unsupported content and transient failures
   receive distinct version outcomes and reason codes; one bad document does
   not stop the next file.
5. After a successful parse, Worker closes `extract_file` and queues
   `embed_file` together. Embedding failure leaves committed source text and
   keyword indexes usable. If first dispatch failed after the parse committed,
   an explicit extract retry repairs a missing index job without re-parsing;
   an existing index job retains its own state and retry policy.
6. `GET /roots/{root_id}` reports stage counts of the *current* versions;
   `GET /files?root_id=` lists one row per file.
7. `POST /roots/{root_id}/scans` rescans; `POST /jobs/{job_id}/retry` requeues
   a failed job. Both refuse when work is already live for the same target.
   A scan reuses unchanged versions and does not implicitly retry a failed
   extraction. Source files remain unchanged by every application operation.

### Search, source evidence and review

`POST /search` applies root/file scope, current-version identity and source
availability checks, returning canonical chunk IDs. `GET /evidence/{chunk_id}`
revalidates mount containment, authorization, current version, SHA-256 and byte
size before returning text and its physical page. Changed, missing, historical
and revoked sources have distinct refusal codes. Paused roots keep read access
while refusing new work.

Version relation reads return bounded candidates with their evidence chunk,
label and entity UUID. The UI can confirm, reject or select an existing entity
as a correction target. Review writes repeat source/evidence validation and
append a new revision; stale revisions return `409 review_conflict`. Reprocessing
preserves unchanged chunk/relation IDs and review history. The frontend uses
these real routes through `/api`, and explicit mock mode remains labelled.

### State vocabulary as served

Versions expose `discovered`, `extracting`, `basic_ready`, `enriched`, `failed`
and `unsupported`. `basic_ready` guarantees committed source text and keyword
indexes; semantic availability additionally depends on compatible token vectors
and local model readiness. `failed` and `unsupported` carry reason codes.
Job: stored as `pending` / `claimed` / `completed` / `failed`, but `claimed` is
served as `running` so the client sees one vocabulary.

### Verification of the W7 implementation

The [31 October evidence set](../submissions/week07/evidence/20261031-w7/)
records real Compose HTTP/Worker/PostgreSQL workflows, browser acceptance,
model readiness and degradation, source/version refusals, explicit failed-job
retry, append-only review and restart persistence. Linux tests run from the
rebuilt application image without a source bind mount. Symlink containment and
FIFO handling have passed there: escaped links are refused, linked directories
are not traversed, and FIFOs are recorded without opening them. The earlier
Windows-only inability to exercise these cases is no longer an unverified W7
boundary. PostgreSQL migration and queue checks complement the faster SQLite
route tests; SQLite alone does not establish PostgreSQL behavior.

### Known limits of this build

- manual scans only, no filesystem watcher;
- one worker; no claim token, lease, `FOR UPDATE SKIP LOCKED` job claim or
  automatic backoff. Multi-worker execution and automatic recovery of jobs left
  `claimed` by a crashed worker remain outside W7;
- text PDFs only; encrypted, damaged, image-only and unsupported-format files
  remain visible with reason codes; OCR is outside W7;
- source access is local and read-only; move/rename operations, overlapping-root
  rejection and purge are deferred capabilities;
- root lifecycle rules are enforced, but W7 has no lifecycle management UI/API;
  pause/revocation refusal tests explicitly record their direct database state
  injection rather than presenting it as a user-facing feature.
