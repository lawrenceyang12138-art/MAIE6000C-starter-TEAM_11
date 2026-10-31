# In-Class Studio: API and Service Boundary Design

Project: SourceLens - MAIE 6000C Team 11
Prepared: 2026-10-10

This document uses the [project brief](../README.md), [architecture proposal](architecture.md), and [Week 4 project plan](../submissions/week04/README.md) to answer the interface questions from the in-class screenshot.

Scope: this document describes the target product design, not implemented endpoints. The current code is still the course starter case-triage flow; folder authorization, scanning, search, graph views, and human review are not implemented. The current implementation check is at the end. Exact request/response JSON, error-code enums, and success codes that are not yet agreed must be confirmed when the W5 contract is frozen.

## 1. Primary workflow interface table

Workflow: choose a folder inside a read-only mount -> API authorizes it and persists a scan job -> Worker scans, extracts, and indexes -> user checks progress, searches, and inspects evidence; failures can be explicitly retried.

| Method / Path | Caller | Request | Success response | Errors | State/data changes | Auth / retry notes |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /roots` | Local browser UI, triggered by the file owner | `mount_id`, `relative_path`; accepts only a relative directory inside a configured mount, never an arbitrary host path or client-supplied processing state | `202 Accepted`; returns `root_id`, `job_id`, and a `pending` scan Job without waiting for scanning or AI work | `422` invalid input; `403` out-of-scope path, escape link, or invalid source; `404` unknown mount; `409` incompatible directory state. Mount unavailability/read failures must be visible; a database write failure must not be reported as accepted | In one transaction, save directory authorization and create a `scan_root` Job; Root authorization is `active`, Job is `pending`; do not enumerate, parse, or analyze files in the request | Validate local session, Origin/Host, mount, and path scope; read source files only. On timeout, confirm whether the request was accepted; do not assume duplicate POSTs are request-idempotent |
| `GET /jobs/{job_id}` | Local browser UI polling job progress | Path parameter `job_id`; no request body | `200 OK`; returns target, type, status, `attempts`, timestamps, and a redacted `error_code` when present. A failed Job can still be read successfully | `404` job not found; `403` target outside the authorized scope or invalid request source | None; read committed database state, do not trigger processing or mark the job successful | Validate local session and target scope; read-only requests may retry, and the frontend polls with an interval. Root and file aggregate progress use additional read endpoints |
| `POST /jobs/{job_id}/retry` (action endpoint) | Local browser UI after the user fixes an issue | Path parameter `job_id`; the minimum contract needs no business body; clients cannot submit new state, attempt counts, or AI results | `202 Accepted`; returns the job identity and `pending`, meaning retry queued rather than processing succeeded | `404` unknown job; `403` unauthorized; `409` job is not retryable, target version is stale, directory state disallows work, or an active job already exists for the same target/type | After validation, move a failed Job from `failed` to `pending`; preserve attempts/history, do not set the file version ready or write AI output directly | Protect local session and Origin/Host; re-check authorization and current version; prohibit duplicate active work. Worker manages transient retries with bounded backoff |

`pending` is a Job state and must not be confused with Root authorization state `active`. A completed `scan_root` Job does not mean every discovered file has completed extraction or AI enrichment; progress should combine file stages and queue aggregates.

The screenshot allows a PATCH or action endpoint, so the third row uses the W7 retry action instead of forcing the R1 pause/resume interface into the initial contract.

## 2. Supporting interfaces for the product loop

These endpoints are also part of the W7 proposal; they do not all need to fit into the three screenshot rows.

| Method / Path | Caller | Request | Success response | Errors | State/data changes | Auth / retry notes |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /mounts`; `GET /mounts/{mount_id}/directories` | Local UI | Configured mount ID and relative directory within the allowed scope | `200`; mount ID/label and browsable child directories | `404` unknown mount; `422` invalid input; `403` out-of-scope path/invalid source; distinguish unavailable source from an empty directory | None; browse configured scope only | Never browse arbitrary Windows paths; reads can be retried |
| `GET /roots`; `GET /roots/{root_id}` | Local UI | Visible scope; single reads use `root_id` | `200`; authorization scope, availability, scan state, and counters | `404` unknown Root; `403` unauthorized | None | Authorization success does not mean AI completion; distinguish empty, unavailable, and in-progress states |
| `POST /roots/{root_id}/scans` | Local UI for a manual rescan | `root_id`; no need to submit a host path again | `202`; Root/Job IDs and `pending` state | `404` unknown Root; `403` unauthorized; `409` incompatible state or duplicate active work | Create a follow-up scan Job; never scan files inside the API request | Reuse the original authorization scope; reuse unchanged file versions and avoid duplicate active work for the same target/type |
| `GET /files`; `GET /files/{file_id}` | Local UI | Root/status filters; single reads use `file_id` | `200`; file identity/location, current version, processing stage, redacted failure reason, and related candidates | `404` file not found; `403` unauthorized; `422` invalid filter | None | Never present historical-version snippets or edges as current results |
| `POST /search` | Local UI with user query | Query text, authorized Root IDs, and filters | `200`; ranked files, current versions, matching snippets/locations, match reason, and capability fallback marker | `422` invalid query; `403` unauthorized scope; `404` unknown identifier. If semantic service is unavailable, explicitly fall back to keyword search rather than pretending to have full semantic results | Do not change files, Jobs, or human decisions; read persisted indexes and request a local query embedding when needed | Use POST so query text does not enter the URL; logs must not record query bodies; retain keyword/metadata search without cloud fallback when AI is unavailable |
| `GET /files/{file_id}/preview`; `GET /files/{file_id}/evidence` | Local UI inspecting sources | `file_id` and expected version; never an arbitrary path | `200`; authorized, version-checked read-only preview or snippet/page/location evidence | `404` unknown file; `403` unauthorized; `409` stale version. Missing/unreadable source must be visible and must not look like no search results | Never write source files; when source identity changes or disappears, record stale/missing and request re-verification, suppressing invalid current evidence | Check scope, source existence, and content identity on every access; cached text does not prove that the source is still valid |
| `GET /graph` | Local UI | Root IDs, focus file/entity, filters, and bounded-neighborhood limit | `200`; nodes, edges, evidence references, review state, and explicitly marked similarity relations | `422` invalid filter/limit; `404` unknown focus; `403` unauthorized | None; build the view from current versions and valid human decisions | Return only a bounded neighborhood in the requested scope; never label similarity recommendations as factual relations |
| `POST /relations/{relationship_id}/reviews` | Local UI for the file owner to confirm/correct/reject a relation | Relationship ID, source version, expected review revision, decision; optional corrected entity/relation type and reason | New review record, revision, and effective relation; `201` for a new record is recommended but not yet fixed in the proposal | `422` invalid decision/correction; `404` relation not found; `403` unauthorized; `409` stale source version or review revision conflict | Append to `reviews`; effective state becomes confirmed/corrected/rejected; preserve original AI assertion and review history | Protect local session and source; use optimistic concurrency. On conflict, read the latest result before retrying; Worker cannot overwrite a user decision |
| `POST /files/{file_id}/tags` | Local UI adding a topic tag | Current source version, topic tag, and optional evidence snippet | `201`; topic entity, user-sourced `tagged_with` relation, and review record | `422` invalid tag/evidence; `404` file not found; `403` unauthorized; `409` stale version | Store user-sourced entity/relation/review; never fabricate AI analysis or citations | Usable without AI; verify submitted snippets; never modify source files |

### R1 management interfaces

| Method / Path | Request / response | API / Worker boundary |
| --- | --- | --- |
| `PATCH /roots/{root_id}` | User changes `monitoring_enabled` or pauses/resumes; returns saved authorization settings/state, with exact JSON and success code still pending | API performs `active <-> paused` and monitoring changes; resuming triggers a re-check. Pause does not revoke read authorization, and safe in-flight work may finish |
| `GET /roots/{root_id}/export` | Returns a local metadata export with file/version references, entities/relations, evidence locations, source, and review records | Read-only export; does not copy source files and does not re-authorize another directory |
| `DELETE /roots/{root_id}` | Explicit user confirmation; returns `202` and a cleanup Job ID | API changes Root to `revoking`, hides it from search/graph immediately, and queues `purge_root`; cleanup Worker changes it to `revoked` after completion. Source files are untouched |

## 3. Eight questions from the screenshot

### 1. Which endpoint begins the workflow?

`POST /roots`. After the user submits a mount ID and relative directory, the API saves authorization and the first scan Job in one transaction and returns `202` with durable identifiers. Browsing mounts is a preceding selection step; later rescans use `POST /roots/{root_id}/scans` without creating a second authorization.

### 2. Which fields are accepted from the user?

The initial input is `mount_id` and `relative_path`. The user selects a directory inside a pre-authorized read-only mount, not an arbitrary absolute path.

Later requests may submit query text, authorized Root/filter identifiers, expected source version, review revision, confirm/correct/reject decision, optional corrected entity/relation type/reason, and manual topic tags. R1 adds pause/resume, monitoring settings, and explicit removal confirmation. Clients cannot set job state, attempts, processing time, content hashes, vectors, or AI output.

### 3. Which fields are generated by the system?

The system generates stable Root/File/Version/Job/Chunk/Analysis/Entity/Relationship/Review IDs, UTC timestamps, content hashes, version links, job type/state, attempts, schedule time, claim token/lease, redacted error codes, scan counters, and the last successful scan time.

The parser produces text and locations; local models produce embeddings, candidate tags/entities/relations, and model/rule provenance; Worker validates and publishes these results; the service assigns a new review revision and records the actor. AI candidate scores are ranking signals, not calibrated correctness probabilities.

### 4. Which status changes may the API make?

W7: create valid directory authorization and a `pending` scan Job; validate and perform an explicit `failed -> pending` retry; append a review revision so an effective relation becomes confirmed/corrected/rejected. During preview verification, the API may record source changes/missing state and request re-verification.

R1: Root `active <-> paused`; monitoring changes; on removal, `active/paused -> revoking` plus a cleanup Job.

The API must not let a client set a Job directly to `running/completed`, set a file version to `basic_ready/enriched`, or fabricate AI output. Saved authorization, queued work, or a successful review write does not mean background processing succeeded.

### 5. Which status changes belong only to the Worker?

Worker/lease recovery owns Job `pending -> running -> completed`, `running -> retry_wait/failed/canceled`, `retry_wait -> pending` after backoff, and stale-work cancellation.

Worker owns file version `discovered -> extracting -> basic_ready -> enriched`, parser failures, `unsupported`, retries, and stale extraction returning to `discovered`. The scan Worker creates version-level extraction work and checks source existence. The R1 cleanup Worker performs Root `revoking -> revoked` after cleanup.

Worker cannot change a user review decision; the AI service returns suggestions only and does not write database state. If AI enrichment fails, a file version may remain `basic_ready`; already committed searchable text must not be deleted.

### 6. What is the visible failure response?

Synchronous requests distinguish `422` invalid input, `403` out-of-scope/invalid source, `404` unknown identifier, and `409` version/review conflict or incompatible state. Directory/model unavailability must have an actionable reason; database unavailability must not return an accepted response. W5 will finalize mappings and error enums; this document does not claim that they are implemented.

Asynchronous requests may return HTTP `200` from `GET /jobs/{job_id}` with business data `status=failed`, a redacted `error_code`, and attempt information. The frontend shows the failed stage, a safe reason, and an available retry action. This differs from the read endpoint itself failing. Other valid files continue processing.

Fallback: when AI/embedding is unavailable, clearly show reduced semantic capability while retaining keyword/metadata search, source access, valid graph data, and manual tags; parser failures must not create fake text. The UI must distinguish no results, still indexing, source unavailable, and AI fallback without exposing sensitive paths or raw stack traces.

### 7. Which endpoint will be demonstrated in Week 7?

The primary entry point is `POST /roots`, but W7 targets a complete vertical slice rather than only returning a Job ID:

1. Select a text-PDF collection with subdirectories inside a read-only mount and receive `202` from `POST /roots` immediately.
2. Use `GET /jobs/{job_id}` and Root/file reads to show asynchronous scanning, extraction, and indexing state.
3. Use `POST /search` for cross-directory keyword/semantic retrieval.
4. Use preview/evidence reads to verify the current version, page, and snippet, then show a basic topic/person/project neighborhood through `GET /graph`.
5. Use a reviews endpoint to save one confirm/correct/reject decision.
6. Show explicit failure and retry/recovery, and prove that data and review records remain readable after a normal service restart.

These are planned demonstration requirements, not product tests passed in this starter. W7 excludes OCR, continuous monitoring, and file move/rename operations.

### 8. What will be cut if the interface design becomes too broad?

Cut file organization first: move, rename, executable preview, operation history, and undo are stretch capabilities, not R1 acceptance gates; the core API and mounts never grant source write access.

Then simplify advanced graph layouts, full-graph visualization, non-core recommendations, and extra dashboards. Keep authorized directories, persistent asynchronous processing, search, source evidence, a basic graph, human correction, visible failures, and privacy boundaries.

W7 is limited to manual scans of text PDFs. Monitoring, DOCX/TXT/Markdown, OCR, a fully declared entity taxonomy, metadata export, and directory-authorization revocation are R1 core and must not be silently removed. Revoking directory authorization is distinct from undoing a file move.

## 4. Service boundary and current implementation check

The API accepts user authorization, queries, and reviews, then persists and returns them. Worker processes queued file work, validates results, and commits them. The internal AI service handles bounded text and model inference only; it has no source-directory, source-write, or database-write access.

`POST /internal/analyze` is the proposed Worker -> AI contract: it accepts versioned, identified/location-aware chunks and returns entities/relations plus evidence candidates for validation. `POST /internal/embed` serves Worker chunk vectors and API query vectors. It is inaccurate to say that only Worker calls AI; short-lived query embeddings from the API are an intentional exception. Instructions in file text are always untrusted data and cannot expand authorization or trigger tools.

| Currently implemented route / behavior | Inspected evidence | Difference from proposed product |
| --- | --- | --- |
| `POST /cases` accepts title/description and returns `201` with case/job | [API code](../services/api/app/main.py), [input/output models](../services/common/schemas.py) | Creates Case `queued` and Job `pending`; it is not the directory-scan entry point |
| `GET /cases/{case_id}` and `GET /jobs/{job_id}` | [API code](../services/api/app/main.py) | Returns starter Case/Job records; current Job IDs are integers while the target proposal uses UUIDs and different fields, so this is not the final product contract |
| Worker `pending -> claimed -> completed/failed` | [Worker code](../services/worker/app/main.py) | Does not implement the proposed lease, `running/retry_wait`, automatic requeue, or retry action |
| Worker calls `POST /triage` and saves label/summary/confidence | [AI code](../services/ai/app/main.py), [persistence models](../services/common/models.py) | Uses keyword rules and text shortening, not local semantic retrieval or entity models |
| PostgreSQL volume, Alembic, health checks, metrics, and test skeleton | [Compose](../compose.yaml), [initial migration](../alembic/versions/20260713_0001_create_initial_tables.py), [integration test](../tests/integration/test_api_case_flow.py) | Reusable foundation; existing tests do not prove directory indexing, the product contract, or PostgreSQL restart acceptance |

This document only adds the class design artifact; it does not modify code, the database, source files, or existing project proposals, and it does not claim product acceptance has passed.
