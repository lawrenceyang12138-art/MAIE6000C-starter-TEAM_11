# Week 13 evidence index and acceptance ledger

**Status (2026-11-28, SGT):** A's 11:50 handoff identifies `7a9fa8087d304f7c126fdc290dc21a98334b7972` ([PR #18](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/pull/18)) as the post-merge integration baseline. It adds two handoff docs over A's tested runtime `f1091de44ffdc125a133ba78133c411f9137ebac`; it does not include the D locator patch. D executed [real browser tests on local candidate `b3bbb2e0b73d9ba45c6c19c01680bdbb7bc77702`](d-browser-20261128.md). Neither the team's frozen final SHA nor a same-candidate C sign-off has been received. No published `w13-final` was found in the fetched refs.

## Current format gates

| Format | C verification on candidate | D real browser on candidate | W13 decision |
| --- | --- | --- | --- |
| PDF with readable text layer | Not received | Pass: two physical-page controls, rejections and same-volume read-back; separate Hybrid control | Required fallback ready for D's rehearsal; not jointly cleared |
| UTF-8 TXT | Not received | Pass: EN/ZH keyword and `invalid_encoding`, genuine ordinal, unchanged rescan | Excluded pending C and release approval |
| Markdown (literal text) | Not received | Pass: EN/ZH keyword and `empty_text`, genuine ordinal, unchanged rescan | Excluded pending C and release approval |
| DOCX body paragraphs | Not received | Pass: EN/ZH keyword and `docx_corrupt`, genuine ordinal, same candidate images and unchanged rescan | Excluded pending C and release approval |

**Jointly cleared support list:** none recorded. D's non-PDF result is limited to the exercised keyword cases; full input-limit coverage, changed-source browser rejection and non-PDF semantic/hybrid were not checked in that run. Scanned PDF OCR, image/OCR/visual models and audio/video are out of scope. Other limits are in the [Week 13 README](../README.md#4-verification-and-limitations).

**Upstream evidence, not C/D acceptance:** PR #13's parser work was corrected and re-landed in [PR #15](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/pull/15); [PR #14](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/pull/14) bypasses PDF navigation for unpaged text. The [A handoff](../../../docs/w13-final-candidate.md#verification) reports real Worker/API results at `f1091de`: 12 readable / 1 rejected in `regression` with flags off, unchanged PDF hits with flags on, and one successful keyword/evidence probe each for TXT, MD and DOCX. The handoff specifically leaves UI rendering and non-PDF semantic/hybrid unchecked. The [C mixed-fixture handoff](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/21fa87a1b0c1ae90ffdf7dd67b16203430ac945a/docs/format-validation/role-c-handoff.md) specifies 12 frozen inputs but reports **UNVERIFIED**, not a test execution or assent. Both release flags default off: TEXT covers TXT/MD together; DOCX can be controlled independently.

| Required human checkpoint | Status |
| --- | --- |
| A: code SHA and candidate API/Worker verification, plus PDF rollback | Received: [candidate](../../../docs/w13-final-candidate.md) and [earlier PDF baseline with Job ID and rescan/restart](../../../docs/w13-pdf-baseline.md). It does not approve a later D package. |
| B: parser/format boundaries and current per-format source comparisons; frozen gold review | Implementation merged; separate human gold review remains pending in [freeze.json](../../../fixtures/search/w13-v1/freeze.json). |
| C: positive/negative search and Worker evidence on the current candidate | Frozen fixture handoff received, but no same-candidate execution/sign-off received. |
| D: browser and demo/limits acceptance on the assembled candidate | Executed: [dated local candidate evidence](d-browser-20261128.md). Applies to this SHA and the recorded configurations, not an untested tag or a replacement commit. |
| Team release approval and benchmark threshold | Not recorded; threshold in the freeze is unset |
| Named release/submission owner, tag and Canvas read-back | Owner not confirmed; no tag push, submission or receipt from this preparation |

## What was actually checked for this preparation

| Item | Result and boundary |
| --- | --- |
| Course requirements | The supplied Canvas screenshot shows `Start Assignment`, `Saturday by 5:30pm`, 100 points and a text entry box; the HTML export contains the exact template and repository/system requirements. The course Assignments URL redirected to Canvas login in a read-only check. No authentication, upload or submission was performed. |
| Services here | Docker Desktop connected on Nov 28 (engine 29.9.2). The live D PDF, mixed and AI runs used separate Compose projects and project-owned volumes. The old stopped projects are not evidence. |
| Frontend engineering check | After syncing A's integration, frontend **105/105** and interface contracts **62/62** passed; the D Docker frontend was built for API mode. The [UI tests](../../../frontend/src/search-evidence.test.jsx) use controlled HTTP fixtures and are separate from the live runs. The upstream [public error-code handling](../../../frontend/src/api/http-adapter.js) supersedes D's draft duplicate change. |
| Real browser and durability | The [local reports](d-browser-20261128.md) cover PDF with parsers off, a 12-file/10-query mixed run with parsers on, immutable rescan, PDF same-volume recreation and one effective, non-degraded PDF Hybrid query. No recording or team sign-off is implied. |
| Frozen sample identities | Read-only Git blob check: all 28 W13-v1 files match their manifest SHA-256 and size at the baseline. Fourteen old working copies do not. Use correct bytes from a clean checkout. |
| Offline artifact | The [PDF cue card](../../../output/pdf/team11-w13-pdf-demo.pdf) uses actual frozen PDF bytes. Strict offline read confirms `doc01.pdf` has two pages, with `Marker01P1` on physical page 1 only, SHA-256 `cf136f2dca47a4f8d3dc00bf4061f4ef746287ee7a92e8eea4bc391ba8e48483`. The frozen negative control extracts no text. The card was rendered and visually checked, and regenerated byte-identically. See the [generator](../tools/build_pdf_demo_card.py). This tests fixture provenance and the artifact, not live processing. |

## Historical evidence (not current sign-off)

| Evidence | Scope |
| --- | --- |
| [W7 acceptance](../../../docs/w7-acceptance.md) and [W7 2026-10-31 record](../../week07/evidence/20261031-w7/README.md) | Dated 18/18 automated acceptance, real runs and separately labelled fixture/mock checks. The dates and tested tree in that record apply. Do not roll those numbers up to W13. |
| [Role C 2026-11-23 results](../../../docs/search-validation.md#2026-11-23-validation-results) and [result JSON](../sections/C-validation.json) | Actual PDF retrieval/AI/restart and quality measurements at runtime `5eb12cff3f0eaac0b5b0f4ca1b75524e052de06f`, not current C/D sign-off. |
| [C validation runbook](../../../docs/search-validation.md) and [gold candidate](../../../fixtures/search/w13-v1/README.md) | Reproduction and expected source locations. Automated fixture checks are not independent human gold approval. |

## What to save for a new run

Keep raw artifacts from each isolated run under `work/w13/`, which is ignored. Only index sanitized, shareable evidence for the course. For each C and D run, record:

- Tester and time (SGT), full SHA and clean-tree status, build/image IDs, browser and environment, allowed formats/model state, data mount and fixture hashes, and link to the actual raw evidence.
- Format and positive/negative samples, expected and actual results, root and initial/rescan Job IDs, effective mode, file/version/chunk IDs, physical page or actual ordinal, evidence text/hash, abnormal reason, screenshot and relevant operation/health signals.
- Before/rescan/restart snapshots, the kept database volume and hash comparisons. Record failures/skips and their reasons; not run is not a pass. Demo recording, if produced, must identify its tested SHA and be labelled recorded.
- Separate C and D pass/fail/skip on the exact candidate and enabled-config path; A's build/rollback confirmation, B's actual review, and named release owner approval. A course read-back receipt records the actual tag resolution, assignment entry, link checks, submission timestamp, and second reviewer.
