# Week 13 demo and browser acceptance

**Primary plan:** a live text-PDF workflow in API mode. **Fallback:** the same candidate's verified AI-off keyword path, then the [offline PDF cue card](../../output/pdf/team11-w13-pdf-demo.pdf) if the application is unavailable. The card shows actual frozen fixture text; it is not a recording or acceptance evidence. No video recording is claimed. See the [ledger](evidence/README.md) and [D's actual browser runs](evidence/d-browser-20261128.md).

Local rehearsal on the tested host: [PDF keyword, after rescan](http://127.0.0.1:13084/scan/33) and [PDF Hybrid, with model ready at the test time](http://127.0.0.1:13086/scan/1). Choose **View available files and evidence** on either. These are loopback links to isolated Docker Desktop projects, not stable course URLs. Recheck `/health/ready` and `/setup` immediately before presenting. Keep the optional formats out of the demo until C and D clear them together on the actual release candidate.

## Prepare the isolated PDF stack

1. Start with the full candidate SHA, not a moving branch tip. [D's record](evidence/d-browser-20261128.md) identifies the locally tested assembled candidate; [A's handoff](../../docs/w13-final-candidate.md) records the distinct predecessor scope. In an isolated clean checkout record `git rev-parse HEAD`, worktree status, image identities and ports. Compare the 16 original mounted sample bytes to the [W13-v1 manifest](../../fixtures/search/w13-v1/manifest.json) (`group: w7-compose`); the updated checkout attributes protect these bytes. Older Windows worktrees may not have been rewritten automatically. Do not change the frozen fixtures or clear a team database.
2. For the PDF/AI-off rehearsal, prepare a local `.env` in that checkout from [the example](../../.env.example), with `FRONTEND_DATA_MODE=api`, `FRONTEND_API_BASE_URL=/api`, `EMBEDDING_ENABLED=false`, `EMBEDDING_AUTO_PREPARE=false`, `SOURCE_MOUNTS={"corpus":"/source/corpus"}`, `TEXT_PARSING_ENABLED=false`, and `DOCX_PARSING_ENABLED=false`. API and Worker read `EMBEDDING_ENABLED` from their Compose service env file, not just a shell export. Use a fresh project volume and free loopback ports; don't repoint a shared stack or overwrite its `.env`.
3. In that checkout, with Docker Desktop/Compose running, build and start only the four services below. Omit `ai` for this flow. Use `--no-build` only when A confirms that the images for this project actually came from the same SHA and configuration.

   ```powershell
   docker compose -p team11-w13-pdf up -d --build db api worker frontend
   curl.exe --fail http://127.0.0.1:8000/health/ready
   curl.exe --fail http://127.0.0.1:8000/setup
   ```

   Wait for HTTP 200 on readiness (adjust the port if configured) and confirm setup reports `disabled`. API ready does not imply the model is ready. For the model-enabled/Windows-bridge setup, follow [the startup guide](../../docs/model-startup.md) and [operations](../../docs/operations.md); `python scripts/start.py --no-wait` still builds/starts services and only skips waiting.

## Browser steps and proof to save

1. Open [the local UI](http://127.0.0.1:3000/select) in a real browser. Require **API mode**, no interception or seeded browser state. Open **Example/configured directories**, select mount `corpus` and path `.`, and click **Authorize and start scan**. Save the real `POST /api/roots` 202 with `root_id` and `job_id`, then progress and `GET /api/jobs/{job_id}`. The Worker should settle with persisted ready/rejected versions. Current Compose adds three format probes: with both flags off, expect **19 total / 12 ready / 7 unsupported**, not the earlier W7 16/12/4. A's `regression` subset was 13/12/1 and excludes the abnormal directory.
2. Inspect a rejected file, e.g. `abnormal/no_text_layer.pdf`: expected `unsupported` / `no_text_layer`; demonstrate that a readable neighboring PDF still reaches `basic_ready`. Capture the reason from the UI and `GET /api/files?root_id=...`. This means no extractable text here, not that OCR was attempted. The frozen `regression/unsupported.txt` stays unchanged in the PDF-only run.
3. Choose **View available files and evidence**. Search `Marker01P1` in **Keyword**. Open the hit for `regression/group-a/doc01.pdf`. Repeat for `Marker02P2` in `regression/group-a/doc02.pdf` on physical page **2**, so a hard-coded page 1 would fail. Save the actual `POST /api/search` and `GET /api/evidence/{chunk_id}` responses and inspector screenshot for each hit. Match `file_id`, `version_id`, `chunk_id`, path, ordinal and `page` vs `page_number`. Search's text is a prefix of the canonical passage (up to 2,000 characters); compare that prefix and check evidence `content_sha256` against the fixture. Independently open the original at physical page **1** or **2** and check the full returned passage. A result preview, a navigation fallback, or a similar title is not proof of the original passage.
4. Before rescan, save stable IDs and job counts for this root. Use **Rescan directory** in the real UI, save the new accepted Job ID, wait for completion, and collect the same snapshot again. Compare sets of file, version, chunk and keyword-index IDs and original hashes. A new `scan_root` job is expected; unchanged bytes must not create new `extract_file` or `embed_file` (index) jobs. With AI disabled the initial `embed_file` rows can still represent keyword indexing; that is not inference. Unchanged UI totals alone are insufficient.
5. Save the named DB volume identity, then recreate services with the **same** project, images and volume:

   ```powershell
   docker compose -p team11-w13-pdf up -d --no-build --force-recreate db api worker
   curl.exe --fail http://127.0.0.1:8000/health/ready
   ```

   After readiness, revisit the same root in the browser without authorizing or rescanning; verify the old job and same evidence chunk/identity/text still read, then compare the DB snapshot and source hashes. Never run `down -v` to check persistence.
6. Show API readiness, model setup state, a relevant Worker log and `GET /metrics`. Record the executed SHA, fixture/configuration and any skipped/failed checks. Use the [evidence log format](evidence/README.md#what-to-save-for-a-new-run).

For the locator and read-only checks, use the [W13 Playwright verifier](../../scripts/verify_w13_browser.mjs) with Chrome and the repository's frontend dependencies installed. The `--expect-sha` check verifies the browser runner checkout; also record the Compose image provenance and deployed candidate. Use a fresh output directory for each run:

```powershell
node scripts/verify_w13_browser.mjs --ui http://127.0.0.1:3000 --suite pdf --output work/w13/pdf-browser --rescan
```

This verifier checks original bytes, independent physical pages and live browser/API identities, and can repeat the scan. It does not establish database job deltas or restart persistence alone. To capture both DB snapshots, first run without `--rescan`, then rescan in the UI after taking the first snapshot. Use the verified root ID with the existing read-only DB snapshot functions (`scripts.verify_w7.snapshot` and `identity_sets`). Run the following against the **isolated** Postgres via the API image, replacing `ROOT_ID_FROM_BROWSER` and choosing a different output for each phase:

```powershell
docker compose -p team11-w13-pdf exec -T api python -c "import json,os,sys; from sqlalchemy import create_engine; from scripts.verify_w7 import snapshot,identity_sets; s=snapshot(create_engine(os.environ['DATABASE_URL']),sys.argv[1]); print(json.dumps({'identities':identity_sets(s),'jobs':s['jobs']},default=str))" ROOT_ID_FROM_BROWSER
```

Save the emitted JSON with the browser report. Do not run the whole W7 HTTP/DB verifier against a live delivery database; it imports files and writes synthetic reviews.

## Demonstrate the integrated AI step

In a model-enabled environment **built from the same candidate**, reuse A's verified pinned model cache (no new model downloads on stage). Check `GET /setup` reports `ready` and the target version has compatible token vectors. Switch the browser to Semantic or Hybrid and save an actual search response with the chosen effective mode, plus the verified original passage. Degradation due to model not ready/disabled/unavailable or incompatible embeddings is not AI success. Save a separate AI-off keyword trace to show resilience. If model proof is missing, report the course AI demo step as unverified; don't rename keyword retrieval as AI.

For the observed Hybrid rehearsal on `corpus/regression`, choose `Marker01P1` and open `group-a/doc01.pdf`, physical page 1. The [D record](evidence/d-browser-20261128.md#integrated-local-text-ai--pdf-hybrid-spot-check) identifies the model/result and an offline cache setup caveat: model preparation needs space for a writable lock and manifest even if weights are pre-cached and read-only. Do not enable downloading to recover the demo; keep the verified keyword path available.

## Individually gate TXT, MD and DOCX

In a clean project/volume for the candidate, use **newly imported** fixtures rather than reprocessing the frozen `unsupported.txt`. The [staging script](tools/stage_mixed_fixtures.py) uses C's exact frozen 12-file archive and independent source decoding. After fetching the C fixture branch (if the pinned Git object is missing), run `python -B submissions/week13/tools/stage_mixed_fixtures.py stage` with PyMuPDF or pdfplumber installed. It writes sources, verifier manifest and a read-only Compose overlay to `work/w13/mixed-fixture/`. With that overlay, choose a new Compose project/volume and the tested flag combination, then use the browser verifier with `--suite mixed --manifest work/w13/mixed-fixture/browser-manifest.json`. Preserve the separate PDF-only regression. For each format:

- Use at least two known-good source files (English and Chinese) and one rejected input; record exact fixture names/hashes, keywords and what rejection was expected. For TXT/MD cover the actual UTF-8 boundary and malformed input; Markdown is literal text, not HTML rendering. DOCX is body paragraphs only and also requires A/B's same-config image rebuild, size/container limits and stable rescan.
- With AI unavailable/disabled, wait for the real Worker to publish normal samples as searchable and show a comprehensible error for the bad sample without blocking neighbors.
- Click each actual keyword hit. Match search/evidence `file_id`, `version_id`, `chunk_id`, path and ordinal; compare the search prefix and full canonical passage as in the PDF check. Compare the passage and SHA-256 with independently read original bytes. API pages must be null and the inspector must show **原文片段 #N** using the real ordinal. No PDF page count, navigation, fabricated page or legacy file/pages endpoint on those hits.
- Repeat the PDF positives and negative case with any proposed text formats enabled together. Verify an expired/missing/changed test source refuses to open cached text; use only a separate disposable fixture root for the stale case, and leave the frozen samples untouched. C and D must both record same-SHA, same-configuration evidence for each released format.

Use B's public rejection codes from the assembled candidate. The frontend sanitizes unrecognized codes to a generic failure; a negative case showing only a generic reason does not clear the gate. `TEXT_PARSING_ENABLED` enables TXT/MD together; `DOCX_PARSING_ENABLED` is separate. If TXT or MD fails, don't leave their shared switch on and omit the failed format. Disabling a flag does not erase passages already indexed in a previous database; use a fresh release demo volume.

At the desk, show only the formats in the approved list. If live services fail, use the same frozen candidate's verified run recording, if available, and label it **recorded**. If it is not available, use the cue card for explanation only and state that live verification could not be shown.
