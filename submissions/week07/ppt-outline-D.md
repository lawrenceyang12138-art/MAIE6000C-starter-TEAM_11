# W07 presentation outline: 12 pages (19 October draft)

This is the planned 12-page text outline, including D's detailed pages 10-12.
It is not a finished deck. A/B/C must supply and confirm their real evidence;
unrun scenarios retain a pending label. Use one primary visual and a concise
claim per page, with readable evidence captions and the same visual hierarchy.

| Page | Main claim / title | Primary visual | Evidence / owner |
| --- | --- | --- | --- |
| 1 | File Trace: local, read-only, source-backed document discovery | One document-to-search-to-source flow, followed by team names | Project README; team confirms names |
| 2 | Users need to find a passage and verify its current source | A short running example: query, matched file, page and quote | Product scope; D; representative real example pending B |
| 3 | W07 scope is deliberately bounded | In-scope/out-of-scope table: local text PDFs and evidence; OCR/organize deferred | Week07 README and scope decision; all members |
| 4 | One shared data model connects four modules | A scan, B parse/chunks, C index/search, D UI, one PostgreSQL boundary | Architecture/shared contract; A supplies current diagram |
| 5 | Authorization queues work before processing completes | Root/Job sequence with 202, scan worker, file processing | A's actual request/job/attempt evidence pending; canonical contract |
| 6 | Immutable versions make page evidence traceable | Source PDF page, chunk boundaries and version-bound locator | B's page/chunk audit; current D frozen source locations are smoke checks |
| 7 | Keyword retrieval remains the baseline | Query-to-chunk-to-file aggregation flow, five real query results | C's keyword report; current integrated 5/5 pending |
| 8 | Local semantic search reports capability honestly | Requested/effective mode and degradation examples beside actual Top-3 results | C's model/version, offline/degrade results pending; D UI fixture labelled |
| 9 | M1 must pass three real browser scenarios | First import / duplicate scan / abnormal mix evidence table with IDs and counts | M1 checklist; pending until real runs and member sign-off |
| 10 | Read-only directory authorization establishes the boundary | Directory page and the 202 contract | D details below; distinguish contract fixture from real service |
| 11 | Job state and file-stage counts answer different questions | Progress page and explicit failed-task retry | D details below; A confirms retained attempts |
| 12 | Every accepted claim should resolve to source evidence | Search/evidence plus relation decision states and limitations | D details below; A/B/C true integration evidence pending |

Pages 1-9 are story and evidence slots, not completed module or acceptance claims.
Final PPT/PDF rendering, recording and release freeze follow the later schedule.

## Page 10 — Directory Authorization and File Selection

**Title:** Read-only directory authorization establishes the scan boundary

**Show:** The `/select` screen with the mount selector, relative directory selector, and the request contract panel.

**Key copy:**

- Client submits `mount_id` and `relative_path` only.
- `POST /roots` returns `202 Accepted`, `root_id`, `job_id`, and `pending`.
- The API does not enumerate or parse files inside the authorization request.

**Evidence:** `frontend/src/app.jsx`, `frontend/src/api/adapter.js`, `fixtures/manifest.json`.

## Page 11 — Scan Progress and Status

**Title:** Background scan status is visible while processing stages stay separate

**Show:** The `/scan/:jobId` screen as it moves through pending and running to completed.

**Key copy:**

- The page polls a read-only Job endpoint.
- The demo makes `12 normal / 3 abnormal / 1 unsupported` visible.
- A completed scan Job does not claim that every file has completed extraction or AI enrichment.
- Failed-Job retry requires a separate explicit action; accepted pending means queued.

**Evidence:** `frontend/src/lib/scan.js`, Mock progress sequence, `submissions/week07/ui-acceptance.md` D-03 to D-05.

## Page 12 — Results, Evidence, and Fallbacks

**Title:** Current-version results ship with page-level evidence

**Show:** The `/results/:rootId` table, an expanded normal PDF, and the failed/unsupported rows.

**Key copy:**

- Results deduplicate on `file_id + version_id`.
- Evidence carries the matching file ID, version ID, source path, and page.
- Empty, parse-failed, unsupported, duplicate-scan, and rollback-protection states remain visible.
- Missing source files and keyword-only capability fallback have separate visible labels.
- Relation quotes start unverified; source failure hides the quote and disables review.
- Confirm/correct/reject appear only after a valid receipt; revision conflicts require a read.

**Evidence:** `frontend/src/api/adapter.js`, `frontend/src/lib/scan.js`, `fixtures/manifest.json`.

**Current UI evidence:** the screenshots `evidence/1019-D/keyword-evidence.png`,
`review-decisions.png`, `review-source-unavailable.png` and `retry-job-accepted.png` were
captured locally but are **not versioned** (5.9 MB total); regenerate them with
`node scripts/capture_d_1019.mjs`. Every image keeps its contract/Mock watermark; these do
not substitute for the pending real M1 runs.
