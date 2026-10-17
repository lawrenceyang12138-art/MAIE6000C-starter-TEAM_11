# W7 Demo Recording Runbook

Use this only after `make w7-check` passes and the Mac is unlocked.

## Preflight

```text
make w7-check
INSTALL_EMBEDDINGS=1 docker compose -p team11_release up -d --build db ai api worker frontend
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:3000/health
```

The AI image must be built with `INSTALL_EMBEDDINGS=1`; the API and worker use
the HTTP embedding client. The model directory must exist at
`models/multilingual-e5-small`.

Open a clean browser tab at `http://127.0.0.1:3000`. Use a fixed viewport and
close unrelated personal tabs before recording.

## Recording sequence

Target: 3–4 minutes. Keep the mouse visible and do not cut away from the
product while it is processing.

1. **0:00–0:25 — Context.** State the read-only promise and show the directory
   page.
2. **0:25–1:00 — Authorize and scan.** Select `corpus`, authorize the root,
   and show the returned root/job IDs and the 16/16 progress state.
3. **1:00–1:30 — Counts.** Read 12 searchable, 0 failed, 4 unsupported, and
   explain that scan completion is not parse completion.
4. **1:30–2:15 — Keyword search.** Search
   `Team 11 synthetic document 01`, open the top result, and show the P1
   version-bound passage.
5. **2:15–3:00 — Semantic search.** Run one description such as
   `打开第十份资料的最后一页`, show the effective mode is `semantic`, and open
   the returned page-3 evidence.
6. **3:00–3:40 — Repeat and close.** Repeat the scan, show 16 files and 16
   versions remain, then state the read-only and limitation summary.

## Backup if something fails

- If the model is unavailable, show the explicit keyword-only degradation and
  say that semantic packaging is incomplete; do not claim a semantic hit.
- If Docker fails, stop recording and fix the environment. Do not use the
  watermarked contract screenshots as a substitute.
- The final video filename is `submissions/week07/demo-backup.mp4`.

## Second-computer check

On the second machine:

1. Copy the repository and `models/multilingual-e5-small`.
2. Build with `INSTALL_EMBEDDINGS=1`.
3. Run `docker compose ... up -d`.
4. Authorize `corpus`, scan, run one keyword and one semantic query, and open
   the evidence page.
5. Record the OS, Python/Docker versions, image digests and the root/job IDs
   in the final manifest.
