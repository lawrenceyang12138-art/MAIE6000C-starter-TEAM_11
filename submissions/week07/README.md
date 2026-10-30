# Team 11 — Week 07 midterm milestone

Checkpoint: `w07-midterm` tag on `develop`.
Status: the read-files vertical slice runs end to end on a local Docker Compose stack —
authorize a read-only folder, scan it, parse and index the text, search it, and open the
source passage behind a hit. Everything below was measured on this branch, not projected.

Roles: A owns mounts, scanning, the root/version model, job assembly and the API surface;
B owns parsing, evidence, relations and review; C owns retrieval and index configuration;
D owns the UI, the browser-side contract and the milestone materials.

## 1. What currently works

One sentence: a user picks a folder inside an allowlisted read-only mount, gets a durable
scan, watches per-file progress, searches the text, and reads the exact page a hit came
from — with the version pinned to the bytes on disk.

Measured on 2026-10-21/22 against the fixed 16-file corpus:

| Step | Result |
| --- | --- |
| Authorize + first scan | 16 files, 16 versions, one `scan_root` job |
| Parsing | 12 `basic_ready`, 4 `unsupported` with reasons: `corrupt`, `encrypted`, `no_text_layer`, `unsupported_format` |
| Indexing | 12 `embed_file` jobs, one per ready version, all `completed` |
| Rescan | 0 new file rows, 0 duplicate versions or jobs |
| Database after 11 scans across two roots | 29 files, 29 versions, 64 jobs — one version per file |
| Restart and container recreation | same roots, same counts, originals' SHA-256 unchanged |
| Relevance | keyword search returns the expected passage; semantic mode degrades visibly without a local model |

The API serves 22 routes: mounts, directories, roots, rescans, jobs and retry, files,
evidence, relations, review, search, plus the starter's case routes and health/metrics.
The frontend consumes them through a same-origin `/api` proxy and validates every field
it reads.

**What "works" does not include**: no filesystem watcher (scans are explicit), one worker
(no claim lease, no skip-locked claim, no automatic backoff), no OCR, no move detection,
no purge, and overlapping authorized roots are not rejected. Symlink-escape rejection is
implemented but only verifiable on a host that can create symlinks — the two cases skip on
Windows.

## 2. Live demo sequence

Five beats, in the order the rubric asks for them. Each has an observable artefact; none
needs narration to be believed.

| # | Beat | Action | What the reviewer sees |
| --- | --- | --- | --- |
| 1 | Input enters | Pick `corpus` → `regression` in the UI, press authorize | `POST /roots` → `202 {root_id, job_id, status: "pending"}` |
| 2 | Persisted state change | `GET /roots/{root_id}` | `file_counts` moves from 0 to 13 total, 12 `basic_ready`, 1 `unsupported` |
| 3 | Async worker step | `GET /jobs/{job_id}` and `docker compose logs worker` | `pending → running → completed`; 13 `extract_file` + 12 `embed_file` jobs |
| 4 | Persisted output | `GET /files?root_id=`, then search and open a hit | one row per file, then the source page with version, page and excerpt |
| 5 | Operational signal | `GET /health/ready`, `GET /metrics` | readiness ok; request counters and job counters move |

Fallbacks if the live demo misbehaves: `submissions/week07/demo-script.md` (six-step
script), the recorded run JSONs in `submissions/week07/evidence/`, and the commands in
`docs/operations.md`. Any step that fails is reported as failed on the spot — the contract
for this milestone is an honest slice, not a flawless one.

## 3. Current implementation status

### Implemented

- **Mounts and authorization.** Allowlisted read-only mounts, relative-path resolution with
  canonical containment, symlink-escape rejection, `404 unknown_mount`, `403 path_out_of_scope`.
- **Scanning and versions.** One `file_versions` row per distinct content, `current_version_id`
  moved in the same transaction as the job, revert handling that moves the pointer back,
  `missing` presence without deleting history, idempotent rescans.
- **Jobs.** Durable `scan_root` / `extract_file` / `embed_file` jobs; atomic claim-and-enqueue
  under a root row lock; `POST /jobs/{id}/retry` guarded by a conditional state update;
  lifecycle refusals for paused, revoking and revoked roots.
- **API surface.** The seven routes the frontend needs, plus flattened `POST /roots`,
  `GET /roots/{id}` with stage counts, and `GET /jobs/{id}` with a public status vocabulary.
- **Search and evidence.** Keyword, semantic and hybrid modes with explicit degradation;
  evidence bound to file, version, page and ordinal; relations and review with optimistic
  concurrency.
- **UI.** Folder selection, scan progress, file list, search, evidence inspector, relations
  and review pages; runs against the real service when built with
  `FRONTEND_DATA_MODE=api`, while the default build stays in the labelled simulation.

### Partially implemented

- **Graph view.** Renders candidates from the relation routes; no similarity edges, no
  cross-file traversal.
- **Retry UX.** Available for failed jobs; a job never fails for a damaged document, so the
  control is only reachable on infrastructure errors.
- **Semantic search.** Works when the local embedding model is present; otherwise it
  degrades to keyword and says so.

### Not implemented

- Filesystem watcher; multi-worker safety (leases, `FOR UPDATE SKIP LOCKED`, backoff).
- OCR, non-PDF formats beyond "detected and recorded as unsupported".
- Move/rename detection, root deletion and purge, overlapping-root rejection.
- Symlink-escape verification on Linux (the code is there; the host cannot create links).

## 4. Architecture status

Four services behind Compose: `frontend` (static Vite build, nginx, `/api` proxy, bound to
loopback), `api` (FastAPI), `worker` (polling process, no HTTP), `ai` (embeddings only, and
optional), and `db` (PostgreSQL 16 + pgvector). The canonical tables are `authorized_roots`,
`files`, `file_versions`, `source_chunks` and the search index; `docs/architecture.md`
records the built components and their limits, and `docs/team11-w7-shared-contract.md` is
the authority for route shapes and error envelopes.

Two design decisions are worth naming. First, a content hash never authorizes deletion or
deduplication: identical bytes at two paths stay two records. Second, the pointer means
"latest content observed", not "latest content parsed", which is why a scan moves it and
parsing only records status — serving stale text as current was the one defect the review
treated as blocking.

## 5. Current evidence of integration

| Boundary | Evidence | What it proves |
| --- | --- | --- |
| DB write path | `evidence/scan-idempotency.md`, `evidence/m1-catalog.md` | files/versions/jobs created once per content, across 11 scans |
| API path | `tests/integration/test_api_w7_routes.py`, frontend adapters | request/response shapes the browser actually validates |
| Worker path | `evidence/scan-run.json`, worker logs | dispatch, completion and terminal states per job type |
| AI path | `docs/search-integration-handoff.md`, degraded-mode tests | keyword stays usable without the model; degradation is visible |
| Operational signal | `docs/operations.md`, `/health/*`, `/metrics` | readiness, counters and troubleshooting steps |
| Persistence | `evidence/restart-v1.md` | restart and container recreation keep roots, counts and hashes |

## 6. Testing and verification performed

```bash
pytest tests/unit tests/integration -q      # 222 passed, 10 skipped
ruff check .                                # clean
SEARCH_TEST_DATABASE_URL=... pytest tests/unit tests/integration -q   # 230 passed, 2 skipped
python scripts/w7_evidence_probe.py --out submissions/week07/evidence/scan-run.json
```

- 10 skips are honest: two symlink cases the Windows host cannot create, eight PostgreSQL
  cases that need a database.
- The queue invariants have PostgreSQL concurrency tests (concurrent rescans, concurrent
  authorizations, stale retries against a worker claim/completion). Each was mutation-checked:
  removing the guard turns them red.
- Security refusals are enumerated in `evidence/security-check.md` (19 cases).
- Known limitation of the suite: route tests run on SQLite, so they prove the HTTP contract,
  not PostgreSQL behaviour; the compose stack covers the positive path end to end.

## 7. Risks and revised scope

| Id | Risk | Severity | Owner | State at freeze |
| --- | --- | --- | --- | --- |
| R1 | Seven file-management, evidence, relation and retry routes not assembled | P0 | A / B | **Closed** — merged in PR #6 (2026-10-23) |
| R2 | Fixture error codes do not match the parser taxonomy | P1 | B + D | Open; deferred past the freeze, needs a corpus re-freeze |
| R3 | M1 three-scenario browser run on a clean database | P0 | A+B+C+D | Partially run: scan/parse/index/search/evidence measured; the browser pass with signatures is not |
| R4 | Relation candidates carry no addressable chunk id | P1 | A / B | Open; review stays disabled when a quote cannot be located |
| R5 | Review success envelope is D's expectation, not an agreed contract | P1 | A / B | Open; consumer fails loud on any other shape |
| R6 | Single worker, no lease or backoff | P2 | A | Accepted for W7; R1 work item |

Scope for the second half is narrowed deliberately: local read-only sources, text PDFs,
one worker, small candidate sets, no remote models.

## 8. Plan from Week 7 to Week 13

1. **Correctness debt.** Regenerate the abnormal fixtures against the real taxonomy and
   re-freeze `gold-queries`; add the missing two scenarios to the M1 record.
2. **Queue maturity.** Claim tokens, leases and recovery of expired claims; bounded backoff;
   a multi-worker test.
3. **Scope safety.** Reject overlapping roots; implement root revocation and purge with an
   explicit confirmation path.
4. **Formats and extraction.** OCR for image-only PDFs; keep every unsupported class visible
   with a reason code rather than silently skipping it.
5. **Graph.** Similarity edges marked as recommendations, never as confirmed relations.
6. **Docs and evidence.** Keep `docs/operations.md` and the evidence set regenerable from a
   single command; every number in the report must be reproducible from the repository.

## 9. Artifact index

| Path | What it is |
| --- | --- |
| `submissions/week07/README.md` | this file — the primary artifact |
| `submissions/week07/report.md` | the full milestone report |
| `submissions/week07/demo-script.md` | six-step demo narration with timings |
| `submissions/week07/sections/` | per-role contributions — `A.md` and `D.md` present; `B.md` and `C.md` pending |
| `submissions/week07/evidence/` | scan, security, M1 and restart evidence plus run JSONs |
| `submissions/week07/evidence/1016-D/`, `1019-D/`, `C/` | UI contract reports and retrieval evidence |
| `docs/architecture.md`, `docs/operations.md` | as-built architecture and runbook |
| `docs/team11-w7-shared-contract.md` | route shapes, error envelopes, state vocabulary |
| `scripts/w7_evidence_probe.py` | regenerates the scan evidence against a live stack |
| `submissions/week07/ai-use-statement.md` | AI use declaration for this milestone |

## 10. AI use statement

See `submissions/week07/ai-use-statement.md`. In short: generative tools were used for
drafting documentation and for reviewing code and tests; every number quoted in this folder
came from a command run in this repository, and every claim that could not be reproduced was
either removed or labelled as not verified.
