# C first-start initialization summary — 2026-10-30 (UTC)

Historical verification of local-model initialization on
`feat/c-team-pdf-evaluation`, based on integrated develop commit
`f6f347abad37345f0119c45b3913ce3ca1b6f5b6` with the feature implementation
then uncommitted. These are results of that execution, not current test counts
or a new validation run. [The compact summary](validation-summary.json)
retains measured outcomes and their limitations.

Only the summary is versioned. Raw status timelines, browser recordings,
logs/XML, machine-specific paths and source manifests remain in the local
ignored archive under `work/pr-evidence-backup/`. They are not downloaded by
cloning the repository. No user-selected folder contents are part of this
summary.

## Behavior checked

- `python scripts/start.py` builds the application environments inside Docker,
  preserves `.env`, starts the stack and reports actual preparation stages.
- The AI downloads fourteen pinned public model files, checks SHA-256,
  atomically publishes verified data, loads the CPU model and warms up query
  and passage encoding before reporting ready.
- Parsing, keyword search and source evidence remain usable while AI prepares
  or fails. When AI becomes ready, normal jobs recover missing current-version
  vectors without duplicating live work.
- A real setup failure exposed explicit retry in the UI. HTTP 202 retry led
  through verification/loading/warmup to ready after restoring the file.
- A later launch reused verified model files without network downloads;
  dependency layers were cached and a subsequent unchanged launch skipped build.

## Recorded results

| Check | Historical result |
| --- | --- |
| Cold preparation | 11/11 checks passed; downloading → verifying → loading → warming_up → ready |
| Verified download | 14 files, 2,397,842,839 payload bytes |
| Cold execution time | 2026-10-30 16:40:02 to 16:44:06 UTC |
| Source integrity | 13 source entries hashed; original bytes unchanged |
| Real inference | Query shape 5×128, passage shape 4×128 |
| Early scan recovery | Explicit `ai_unavailable` keyword fallback, then native semantic result for the same chunk/version |
| Real browser retry | HTTP 202; 113 status responses; no page runtime errors |
| Python/PostgreSQL suite | 703 passed, 2 skipped, 0 failures/errors |
| Frontend checks | 48 Vitest, 55 Node tests passed; production build passed |

The two Windows skips were file-symlink privilege and unsupported FIFO cases.
The later [W7 summary](../../20261031-w7/README.md) records their Linux execution.
An intermediate `RemoteProtocolError` was observed before recovery; this summary
does not claim an error-free timeline.

## Model and scope

The model is `perplexity-ai/pplx-embed-v2-late-0.6b`, revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`, using native query/document
encoding and mean token MaxSim, with 128 dimensions per token. Inference uses
local files; no hosted inference fallback is introduced. Existing retrieval
weights and limits were unchanged.

The browser began after the cold download had completed. The historical API
timeline established the download; the browser checked ready and failure/retry.
This startup smoke is not a gold retrieval or page-navigation quality evaluation.
B's human gold review and complete transitive dependency locking are not claimed.

## Reproduction

Follow [the first-start guide](../../../../../docs/model-startup.md) with a
separate Docker project, synthetic read-only fixture mounts and a disposable
database. Docker/Compose and Python are prerequisites. Use the reusable tools:

```powershell
python scripts/start.py
python scripts/verify_model_startup.py --output work/model-startup-verification.json
node scripts/verify_startup_browser.mjs
```

Set the documented API/AI URL and isolated-project overrides for the deployment.
Keep generated outputs under ignored `work/`. A real cold-download reproduction
requires intentionally removing only the inspected model directory as described
in the guide; unit tests alone do not establish a download or build.
