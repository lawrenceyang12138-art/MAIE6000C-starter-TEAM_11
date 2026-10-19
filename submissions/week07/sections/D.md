# Role D: frontend, integration, and evidence

## 19 October update (current)

The content search UI now calls canonical `POST /search` instead of treating the
catalog filter as retrieval. It uses keyword by default, exposes hybrid/semantic
requests explicitly, and shows effective mode and degradation. Result evidence
opens by chunk ID and verifies file/version/path/page/ordinal. Unknown locators
remain unknown; lowercase source refusal codes hide cached text.

Relations and Human Review now have separate functional consumer pages. They
read bounded candidates, show provenance and decision state, verify supporting
source before enabling review, and send an expected revision with each decision.
Corrections name an existing entity ID; no entity is invented. Confirmed state
appears only after a valid service receipt. Duplicate submissions are blocked;
conflicts and uncertain writes require reloading the latest revision.

Candidate quotes are marked unverified until their source is checked. A failed
source read, including an ordinary HTTP 503, hides the stored quote and keeps
review disabled.

Current local verification passes 55 Node contract tests, 21 Vitest tests
(including eleven React workflow tests), the 4,916-module production build, Mock
regression, fixture validation and all ten frozen source-location checks. The
current 10.19 API-consumer browser report has 19 passing scenarios and zero page
errors, including failed-Job retry and failed source-read recovery. These checks
establish D's consumer behavior, not real product acceptance. Node, Vitest and
browser evidence files have been refreshed against the current source.

The failed-Job page also consumes the proposed `POST /jobs/{job_id}/retry`
action: it requires HTTP 202 with the same Job and Root in `pending`, blocks
duplicate submissions, and re-reads status after rejected or uncertain responses.
The current API still needs A to confirm and assemble this route; contract tests
and browser fixtures do not prove backend retry or recovery.

The browser report and watermarked screenshots cover accepted rescan and
failed-Job retry. Pinned playwright-core uses an independently launched installed
Chrome; no open browser profile is accessed. An independently
selected `VITE_MOCK_SCENARIO=relations` sample makes the new screens operable
without an assembled backend; its current report records five scenarios
without HTTP interception and preserves the original frozen 16-file corpus.
Its fictional source and in-memory reviews are simulation only.

Week07 sections 1-5, the revised six-step demo script, M1 checklist and scope
record now exist. Current API route assembly and true scan-to-search acceptance
remain incomplete; no A/B/C approval is impersonated. The relation contract lacks
a directly addressable chunk ID, and the review success envelope still needs A/B
confirmation. See `../ui-progress.md` and `../../../docs/frontend-integration-contract.md`.

## 16 October update

The D frontend now defaults to the real HTTP adapter with no automatic demo fallback. It checks actual 202 acceptance, keeps Job discovery separate from Root file-stage counters, preserves unknown counters, and supports read retries without replaying authorization. Empty, parse-failed, source-unavailable and keyword-only states remain distinct; cached invalid source passages are hidden. The client-side results filter is explicitly not semantic search.

Thirty-five Node adapter/progress tests, nine Vitest adapter/helper tests, the API-mode production build, and eight browser contract scenarios pass. All eight watermarked PNGs have been visually inspected; the browser report records zero runtime errors and `product_acceptance: false`. Ten frozen source-location answers were checked against actual PDF pages. These are numbered synthetic placeholder files, not a representative semantic evaluation. B review is pending. See `../ui-progress.md`, `../gold-queries.json` and `../evidence/1016-D/` for the full handoff and raw evidence.

User authorization unblocked dependency installation and read-only Docker inspection. The generated lockfile is included. Docker inspection found only the frontend running; API/DB/AI/Worker remain created but not started. The unhealthy frontend probe resolves localhost to IPv6 while Nginx listens on IPv4. Both source healthchecks now use 127.0.0.1; no container was restarted or rebuilt. Real integration/screenshots remain incomplete because the repository still has only the starter API. No A/B/C-owned backend, migration or worker was changed; no simulated run is claimed as product acceptance. The notes below retain the historical 14–15 October slice; the current mode, lockfile and verification record supersede historical pending items.

## 10/14-10/15 catch-up status

This catch-up slice implements the missing D-owned demo surface without changing A/B/C-owned Python models, migrations, worker code, or the starter public API.

### Implemented

- `fixtures/` contains two normal subdirectories plus abnormal and unsupported samples: 16 synthetic files in total, split into 12 normal PDFs, 3 invalid PDFs, and 1 unsupported-format file.
- The normal PDFs contain 20 traceable pages in total. `fixtures/manifest.json` records the stable file ID, version ID, relative path, SHA-256, page count, expected status, and expected error code.
- `frontend/` is a React/Vite application with three routes: directory selection, scan progress, and results/evidence.
- The default Mock adapter implements the agreed method names: `listMounts`, `listDirectories`, `createRootScan`, `getJob`, `listFiles`, and `getEvidence`.
- The selection flow returns a visible `202 Accepted` contract with `root_id`, `job_id`, and `pending`.
- The progress page keeps Root authorization separate from Job status and exposes total, processed, normal, abnormal, unsupported, and percentage counters.
- The results page deduplicates by `file_id + version_id`, shows file/version/page/snippet/status fields, preserves duplicate-scan and rollback notes, and expands version-checked evidence.
- The mock includes a missing-source result and a keyword-only capability downgrade so the UI can distinguish unavailable evidence from reduced search capability.
- The frontend is included in `docker compose` as a Node build plus Nginx runtime image, with `3000` exposed, `/health` checked, and SPA route fallback enabled. Mock mode is the default; API mode is build-time configurable through `FRONTEND_DATA_MODE` and `FRONTEND_API_BASE_URL`.

### Known boundary

The current repository still contains the course starter API, not the proposed file-management endpoints. The UI therefore does not claim real backend integration: API mode is an explicit environment switch and is ready for A's final contract.

The frontend dependency versions were pinned directly in `frontend/package.json`. The registry-generated lockfile was pending at the time of this historical slice and has now been generated and verified; use the current installation instructions in `frontend/README.md`.

## Evidence index

- Fixture inventory: `fixtures/manifest.json`
- UI contract and adapter: `frontend/src/api/adapter.js`
- Progress and deduplication rules: `frontend/src/lib/scan.js`
- Acceptance matrix: `submissions/week07/ui-acceptance.md`
- Presentation copy for pages 10-12: `submissions/week07/ppt-outline-D.md`
