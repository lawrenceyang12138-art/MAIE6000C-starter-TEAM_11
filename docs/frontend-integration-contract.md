# D frontend integration contract - 19 October

The current consumer follows `team11-w7-shared-contract.md` sections 6.2-6.6.
This supersedes the historical 16 October proposal below. The shared contract
is an integration target; missing routes still produce visible errors.

## Current D consumer

- Authorization consumes the flat HTTP 202 `{root_id, job_id, status: "pending"}`.
  Public numeric job IDs are accepted; the starter `{id, status: "claimed"}`
  envelope is still rejected. Public job states include pending/running/retry_wait/
  completed/failed/canceled.
- Files accept a null version for discovered/unprocessed records. Missing or
  unavailable `presence_status` prevents source inspection.
- The content search form calls `POST /search` with query, requested mode, top_k,
  root_id and file_id. Default mode is keyword for the M1 path; the user can
  explicitly request hybrid/semantic. Requested and effective modes are shown.
  Degradation stays visible, including for an empty successful response.
- The smaller catalog filter is explicitly separate from content search.
  Search remains usable if file-catalog loading fails; catalog counters stay unknown.
- A search result opens `GET /evidence/{chunk_id}`. Chunk, file, version, page,
  ordinal and relative path must match before displaying the passage. Unknown
  page numbers stay unknown. Lowercase source refusal codes suppress cached text.
  The old API file-evidence list method remains only for historical tests;
  the API-mode UI no longer calls it.
- `/graph` reads `GET /versions/{version_id}/relations`; `/review` adds confirm,
  correct and reject forms. Reads are limited to 20 candidates; empty data and a
  missing endpoint have separate states. Provenance and revision are displayed.
- The shared relation example lacks a chunk ID. D resolves its quote with a
  root+file-scoped keyword search, then opens canonical chunk evidence and
  checks the full quote and selected version/page. If the bounded/deduplicated
  search cannot locate that page, review stays disabled. A/B can improve this
  by returning an evidence chunk ID through an agreed contract update.
- Review sends decision, expected_revision, reason and actor to
  `POST /relations/{relationship_id}/reviews`. Corrections additionally require
  an existing corrected_entity_id; D does not invent entities. Confirmation and
  rejection omit that field. D currently expects HTTP 200 with
  `{decision_revision: expected_revision + 1}`; the shared document leaves the
  success envelope unspecified, so A/B must confirm this response when wiring
  the route. A different response is a visible contract error, never fake success.
- Save is disabled until evidence has been verified. Double submissions are
  blocked, and UI status changes only after a valid server receipt. Revision
  conflict, timeout, network error, 5xx or malformed receipt require a fresh read
  before a further submission. Requests are never automatically replayed.
- Candidate quotes are labelled unverified before source inspection. A failed
  source check hides the stored quote even for ordinary transport/HTTP errors;
  review stays disabled until a later source check succeeds.
- Failed scan Jobs expose `POST /jobs/{job_id}/retry` with no business body. The
  consumer requires HTTP 202 and the same Job/Root identity with `pending`; this
  is a proposed boundary contract, and A must confirm and assemble the route.

The current branch API does not assemble the mount, file, evidence, relation or
review routes. These frontend consumer changes and the fixture browser tests
do not establish a passed M1. Relation pages describe suggestions and human
decisions; M1 pending status is recorded in the submission documents, without
putting project acceptance details into the product flow. No team member's approval is fabricated.

For an operable UI-only sample, explicitly select `VITE_DATA_MODE=mock` and
`VITE_MOCK_SCENARIO=relations` when starting local Vite. This uses the separate
`frontend/src/mock/relations.json`, with one fictional document and three
person/project/topic candidates. It supports in-memory confirm/correct/reject
and revision conflicts; correction uses an existing sample entity ID such as
`entity-replacement`. A full reload resets the sample. It contains no real PDF,
does not change the frozen 16-file fixture, and is never selected by API errors.

## Historical 16 October proposal (superseded)

This is the D consumer contract, derived from the proposed service boundary and the existing UI. It is **not an A-approved backend contract or proof that these endpoints exist**. The inspected API remains the case-triage starter. A should confirm the field names before real integration; differences should be mapped in `frontend/src/api/http-adapter.js`, not hidden by substituting mock data.

## Requests and responses

All successful reads below return HTTP 200 JSON. Collections are arrays, not undocumented `items` envelopes. Identifiers are nonempty strings and are URL-encoded by the adapter. Authentication, origin checks, directory scope, and source-version verification remain server responsibilities.

| Request | Minimum response consumed by D |
| --- | --- |
| `GET /mounts` | `[{mount_id, label, read_only: true, availability}]` |
| `GET /mounts/{id}/directories` | `[{relative_path, label}]`; `.` means the whole configured mount if the server permits it |
| `POST /roots` with `{mount_id, relative_path}` | HTTP **202**, `{root_id, job_id, status: "pending"}`; do not accept a body claiming 202 when HTTP is 200 |
| `GET /jobs/{id}` | `{job_id, root_id, status, attempts?, error_code?}`; status is `pending`, `running`, `retry_wait`, `completed`, `failed`, or `canceled` |
| `POST /jobs/{id}/retry` with no business body | HTTP **202**, `{job_id, root_id, status: "pending"}`; identity must match the failed Job; this means queued, not completed |
| `GET /roots/{id}` | `{root_id, status, availability?, file_counts?}`; Root status is not Job status |
| `GET /files?root_id={id}` | `[{root_id, file_id, version_id, display_name, relative_path, status, ...}]` |
| `GET /files/{id}/evidence?version_id={id}` | `[{file_id, version_id, page, source_path, excerpt, evidence_id?}]`; page is a positive integer and belongs to the requested current version |

Root aggregate example, proposed for A confirmation:

```json
{
  "root_id": "server-generated-root-id",
  "status": "active",
  "availability": "available",
  "file_counts": {
    "total": 16,
    "basic_ready": 12,
    "enriched": 0,
    "failed": 3,
    "unsupported": 1
  }
}
```

`file_counts` describes current file versions, not discovered rows, historical versions, or scan-job completion. All five counters must be nonnegative integers and accounted files cannot exceed total. `basic_ready` and `enriched` are disjoint stages. The UI shows searchable = basic_ready + enriched, abnormal = failed, unsupported = unsupported, and pending = total - searchable - abnormal - unsupported. Missing/invalid counters remain unknown and are displayed as dashes, not zeros or invented success.

When a scan completes but pending file processing remains, polling continues. `basic_ready` does not prove that embedding or AI enrichment succeeded. `failed`/`canceled` stop automatic job polling; read retry is user-triggered. Already accepted files remain accessible from progress regardless of scan completion.

Optional file fields are `page_count`, `sha256`, `source_available`, `capability_status`, `snippet`, `scan_note`, `source_kind`, and a redacted `error_code`. `keyword_only` is a capability downgrade, not a parser failure. `source_available: false`, file states `stale`/`missing`/`unreadable`, and evidence errors `SOURCE_UNAVAILABLE`/`STALE_VERSION` suppress cached passages and evidence rows. Invalid-source snippets are also excluded from the local filter. Evidence must match the selected relative source path and cannot exceed a known page count. A failed evidence version check must return 409, rather than publishing historical evidence as current. The server must recheck source identity on evidence reads; frontend checks do not replace that responsibility.

## Error and retry behavior

- Error bodies may provide `{code}` or FastAPI `{detail: {code}}`. Only recognized safe codes become actionable text; raw detail, traceback, host paths, and unknown job error codes are not rendered.
- HTTP 403/404/409/422/5xx, invalid successful JSON, and the old integer-job schema remain explicit errors, not an empty collection.
- Reads and writes time out after 15 seconds. No request is replayed automatically, and a timed-out authorization asks the user to verify acceptance before resubmitting.
- Submission is disabled while authorization is in flight. Retrying directory/status reads never issues `POST /roots` again.
- A failed Job exposes an explicit retry action. After any rejected or uncertain retry response, the UI re-reads Job/Root state before enabling another submission; it never automatically replays the POST.
- API mode never switches to Mock after a failure. Mock is an explicit `VITE_DATA_MODE=mock` build choice and carries a persistent simulation warning.

The retry row is a proposed D-consumer contract based on `docs/api-service-boundary-design.md`; it is not evidence that the current API has assembled this route.

## Intentionally outside this slice

The 16 October proposal below is retained for traceability only. As of 19 October,
the results form calls `POST /search`, and `/graph` plus `/review` are implemented
as explicit D consumers; they still require the corresponding A/B routes and real
database evidence before they count toward M1. Preview, file mutation, and AI
recovery remain outside this D slice. No Python API/model/migration/worker files
were changed.
