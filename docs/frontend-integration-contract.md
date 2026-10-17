# D frontend integration contract for 16 October

This is the D consumer contract, derived from the proposed service boundary and the existing UI. It is **not an A-approved backend contract or proof that these endpoints exist**. The inspected API remains the case-triage starter. A should confirm the field names before real integration; differences should be mapped in `frontend/src/api/http-adapter.js`, not hidden by substituting mock data.

## Requests and responses

All successful reads below return HTTP 200 JSON. Collections are arrays, not undocumented `items` envelopes. Identifiers are nonempty strings and are URL-encoded by the adapter. Authentication, origin checks, directory scope, and source-version verification remain server responsibilities.

| Request | Minimum response consumed by D |
| --- | --- |
| `GET /mounts` | `[{mount_id, label, read_only: true, availability}]` |
| `GET /mounts/{id}/directories` | `[{relative_path, label}]`; `.` means the whole configured mount if the server permits it |
| `POST /roots` with `{mount_id, relative_path}` | HTTP **202**, `{root_id, job_id, status: "pending"}`; do not accept a body claiming 202 when HTTP is 200 |
| `GET /jobs/{id}` | `{job_id, root_id, status, attempts?, error_code?}`; status is `pending`, `running`, `retry_wait`, `completed`, `failed`, or `canceled` |
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
- API mode never switches to Mock after a failure. Mock is an explicit `VITE_DATA_MODE=mock` build choice and carries a persistent simulation warning.

## Intentionally outside this slice

The current results box filters loaded records in the browser; it does not call `POST /search` and is not a semantic-search implementation. Search integration is scheduled for 17 October. Graph, human review, preview, file mutation, and AI recovery are not fabricated by D. No Python API/model/migration/worker files were changed.
