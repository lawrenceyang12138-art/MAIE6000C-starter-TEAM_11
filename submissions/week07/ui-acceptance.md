# Role D UI acceptance matrix

## 19 October status (current)

Current local checks pass 55 Node contract tests, 21 Vitest tests (11 React
workflow tests), the production build and frozen source checks. Browser evidence
was refreshed against the current source: 19 HTTP-contract scenarios and five
explicit Mock scenarios, with zero page errors. These are UI consumer checks;
the three real M1 browser scenarios remain unrun. See [completion audit](evidence/1019-D/completion-audit.md).

| ID | D-owned behavior | Current evidence | Remaining boundary |
| --- | --- | --- | --- |
| D19-01 | Scoped content search, explicit degradation, chunk evidence | `keyword-evidence`, `keyword-fallback`, `empty-search`, `search-error`, `stale-evidence` screenshots and Node checks | Real assembled file/evidence services and C search evaluation |
| D19-02 | Three entity types, provenance, current version, decision states | `relation-candidates`, `review-decisions`; person/project/topic and confirm/correct/reject | B real candidates and A/B HTTP routes |
| D19-03 | Source failure hides quote; successful recheck enables review | `review-source-unavailable`, `review-source-recovered`; React 503 regression | Real source access and agreed direct chunk locator |
| D19-04 | Append-only review consumer, conflict reload, no duplicate POST | `review-conflict` and React deferred-write tests | Real database revisions and agreed success envelope |
| D19-05 | Explicit rescan and failed-Job retry acceptance | `rescan-accepted`, `retry-job-accepted`; Node and React checks | A's actual retry route and retained attempt records |
| D19-06 | Mobile/tablet/laptop layouts | 375/768/1024 search and review screenshots, no viewport overflow | Real-service acceptance |
| D19-07 | Operable separate synthetic example | Five `mock-relation-*` cases, no HTTP interception or API requests | Synthetic source and in-memory decisions only |

## 16 October status

The current frontend defaults to API mode; Mock must be explicitly selected. The production build, 35 Node contract tests, 9 Vitest adapter/helper tests and 8 browser contract scenarios passed. The browser uses intercepted HTTP fixtures, not the actual backend; all eight screenshots retain NOT PRODUCT EVIDENCE watermarks and were visually inspected. The full record is `ui-progress.md`.

| ID | Scenario | Verified result | Outstanding evidence |
| --- | --- | --- | --- |
| D16-01 | Real adapter accepts authorization | HTTP 202 contract verified in adapter and browser; a single POST, no replay | A's live endpoint and real-service screenshot |
| D16-02 | Job completed while files still extracting | Continues polling independent Root counters | Live Worker/DB evidence |
| D16-03 | 12/3/1 current-version counts | Browser screenshot shows 16 total, 12 basic/enriched, 3 failed, 1 unsupported from fixture Root | Live Root aggregate and real-service screenshot |
| D16-04 | Missing or malformed counters | Unknown/dashes in browser; no progressbar or invented 100%; malformed cases tested in Node | Live schema confirmation |
| D16-05 | API unavailable, invalid JSON, old starter schema | Browser HTTP 503 screenshot: safe error, disabled submission, no Mock fallback; invalid schemas checked in Node | Live API error handling |
| D16-06 | Empty collection | Browser screenshot: empty array distinct from failed/unavailable read | Real empty-scope run |
| D16-07 | Parser failure | Browser screenshot: file and safe failure code retained; zero-page evidence not fetched | B's actual parser failure |
| D16-08 | Source unavailable, stale, missing or unreadable | Source-unavailable browser screenshot: no cached passage/evidence, no evidence fetch; path/page/stale checks in Node | Live source/version changes |
| D16-09 | Keyword-only capability | Browser screenshot: explicit fallback plus remaining version evidence | Live AI-stop check is 17 October work |
| D16-10 | Freeze fixed answers | 10/10 PDF page locations and 16 file hashes checked | B's manual review and representative topical corpus |

The screenshot script `scripts/capture_d_ui.mjs` ran against the API-mode production preview at 127.0.0.1:4173 in a separate headless browser, at 1440×1000. The report records 8/8 passes and zero page runtime errors. Its request-intercepted screenshots retain the NOT PRODUCT EVIDENCE watermark. This does not verify mobile layouts, real AI shutdown, real DB counts or the actual parser. See `evidence/1016-D/README.md` for each screenshot.

## Historical 14–15 October matrix

The rows below preserve the earlier record. Current installation and browser results above supersede the historical environment blockers; they do not retroactively establish live integration.

| ID | Scenario | Expected observable result | Status |
| --- | --- | --- | --- |
| D-01 | Load `/select` | Read-only mount and configured directories are visible | Browser verification blocked: npm dependencies unavailable |
| D-02 | Submit a normal directory | Visible `202 Accepted`, Root ID, Job ID, and `pending` contract | PASS: Node adapter test; browser route unverified |
| D-03 | Poll a new Job | Progress moves from pending to running and then completed | PASS: Node adapter test; browser route unverified |
| D-04 | Complete a normal scan | Counters show 16 total, 12 normal, 3 abnormal, 1 unsupported | PASS: fixture and adapter validation |
| D-05 | Read progress boundaries | UI explains that Job completion does not equal all parsing/AI completion | Source check only; browser route unverified |
| D-06 | Select the empty directory | Scan completes with zero files and results page shows an empty state | PASS: Node adapter test; browser route unverified |
| D-07 | Use an unknown mount | Visible 404-style error with `UNKNOWN_MOUNT` | PASS: Node adapter test |
| D-08 | Submit an unsafe path | Visible 403-style error with `PATH_OUT_OF_SCOPE` | PASS: Node adapter test |
| D-09 | Submit a duplicate active scan | Visible 409-style error with `ACTIVE_JOB_EXISTS` | PASS: Node adapter test |
| D-10 | Open a normal result | File name, file ID, version ID, status, page count and snippet are visible | Data fields present; browser route unverified |
| D-11 | Expand evidence | Evidence contains matching file ID, version ID, source path and page | PASS: Node adapter and fixture validation |
| D-12 | Open failed, unsupported, missing-source, and downgraded results | Error code, source availability, capability fallback, and state note remain visible without stack traces | PASS: data/adapter checks; browser route unverified |

## Manual handoff sequence

1. Run `npm run fixtures:check` from `frontend/`.
2. Run `npm run dev` and open `/select`.
3. Select `normal` and submit.
4. Let the progress page reach completed, then choose “View results and evidence”.
5. Expand `team11-demo-09.pdf` to show three page-level evidence rows.
6. Return to results and point out failed, unsupported, missing-source, keyword-only, duplicate-scan, and rollback-protection states.
