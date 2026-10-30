# First-start local model preparation

From this branch's repository root, run:

```powershell
python scripts/start.py
```

The launcher uses only Python's standard library. Install and start Docker
Desktop with Compose v2 first; the application does not silently install or
reconfigure a machine-wide Docker daemon. No host virtual environment, PyTorch,
Node installation, manual model download, or GitHub token is needed for this
Docker workflow. Internet access and disk space are needed on the first build
and first model download. A previously verified model can run offline.

## What happens automatically

1. Check Docker and Compose. Create `.env` from `.env.example` only if absent;
   an existing configuration is never replaced. New installs use the real API,
   not the labelled UI simulation.
2. Build the runtime and frontend images when their inputs changed or an image
   is missing. Docker installs the pinned Python/AI and frontend dependencies.
   The terminal shows actual package/build logs, not an estimated percentage.
   `work/startup-build.json` records only an input fingerprint; it contains no
   credentials. Unchanged subsequent launches reuse installed images and model
   files rather than reinstalling packages.
3. Start PostgreSQL/pgvector, AI, API, Worker and frontend. The API runs the
   shared Alembic chain, including B's `20261030_0005` C-sidecar migration, before
   serving. No second implicit search migration chain is introduced.
4. The AI preparation task checks its package environment and local model. If
   necessary, download only the pinned model files, verify their fixed SHA-256
   identities, publish the verified manifest, load the model and run warmup.
5. The terminal polls `GET /setup`. Open
   [the application](http://127.0.0.1:3000/select) to see the same backend state,
   download bytes, verification and warmup progress. The web UI is available
   after dependency installation; it cannot display progress before its own
   image exists. An unknown byte total is indeterminate, never a fabricated
   percentage.

The model is `perplexity-ai/pplx-embed-v2-late-0.6b`, revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`. Its query/document token vectors
have 128 dimensions and use native MaxSim. Retrieval weights, chunk limits,
page-navigation behavior and frozen evaluation answers are unchanged.

Only AI receives write access to `./models`, for its cache. API/Worker mounts
of original source files remain read-only. Weights are ignored by Git and are
not uploaded with the branch. Runtime inference uses verified local files; the
preparation downloader is the only startup component that contacts the public
model host. There is no hosted inference or cloud fallback.

## Progress, failures and retries

`GET /setup` distinguishes pending, environment checking, model checking,
downloading, verification, loading, warmup, ready, disabled, error and
unavailable. Stage/byte progress comes from actual work. The model is ready
only after successful warmup; process liveness is not model readiness.

API and Worker do not wait for semantic readiness. During preparation or a
download/inference failure, parsed text, keyword search and original evidence
remain usable; semantic/hybrid search continues to report its requested and
effective mode and explicit degradation. Starting containers successfully does
not prove that the model or all document embeddings are ready.

When the worker observes successful model readiness, it queues ordinary embed
jobs for current parsed versions whose compatible token vectors are missing.
This covers documents scanned while the first download was still in progress.
Only active roots, present files, current `basic_ready`/`enriched` versions and
verified on-disk source identities are eligible. Paused/revoked folders and old
versions receive no new jobs; existing live embed jobs are not duplicated. The
model-ready indicator does not claim these per-document jobs have finished;
search still reports incomplete-vector degradation until their normal indexing
jobs complete.

A failed preparation displays a safe reason and a Retry action. Fix connectivity,
disk space or permissions, then use the UI action or:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/setup/retry -Method Post
Invoke-RestMethod http://127.0.0.1:8000/setup
```

Verified files are reused. Incomplete/corrupt files are not accepted merely
because they exist, and a manifest cannot authorize arbitrary replacement bytes.
The loader and downloader remain pinned to the same model/revision and hashes.

## Configuration and useful commands

Edit `.env` deliberately; restarting the launcher preserves your choices.

| Setting | Default | Meaning |
| --- | --- | --- |
| `EMBEDDING_ENABLED` | `true` | Set `false` for an explicitly keyword-only deployment |
| `EMBEDDING_AUTO_PREPARE` | `true` | Set `false` to prohibit automatic model download; a verified existing model can still load |
| `EMBEDDING_DOWNLOAD_TIMEOUT_SECONDS` | `30` | Network-operation deadline during preparation |
| `EMBEDDING_DOWNLOAD_RETRIES` | `3` | Bounded download retry policy |
| `EMBEDDING_CPU_THREADS` | `4` | CPU inference threads |
| `SEARCH_REQUEST_TIMEOUT_SECONDS` | `10` | Ordinary search-to-AI deadline, separate from startup |
| `FRONTEND_DATA_MODE` | `api` | Explicit `mock` remains simulated and is never selected on API errors |
| `API_HOST_PORT` / `AI_HOST_PORT` | `8000` / `8100` | Local API/AI endpoints |
| `FRONTEND_HOST_PORT` / `POSTGRES_HOST_PORT` | `3000` / `15432` | UI/database host ports |

Published API, AI, database, UI and optional metrics ports bind only to loopback
(`127.0.0.1`), not to all network interfaces. No remote setup access is enabled.

Compose fixes the AI model path to `/models/pplx-embed-v2-late-0.6b`, backed by
the branch's `models/pplx-embed-v2-late-0.6b` host directory. Do not point model
preparation at a user's source directory. Downloads do not inspect evaluation
gold, source PDFs or personal documents.

```powershell
python scripts/start.py --check       # Docker check only; changes no files/containers
python scripts/start.py --no-wait     # start and show UI URL; does NOT assert model readiness
python scripts/start.py --timeout 3600
python scripts/start.py --rebuild     # force build, still allowing Docker layer cache
docker compose logs -f ai
docker compose down                  # stop; retain model files and database volume
```

The launcher exits nonzero on preparation error or wait timeout but leaves
started services running, so keyword search and the progress/error view remain
accessible. Interrupting the wait does not delete data or containers. Do not use
`docker compose down -v` for normal restarts: it deletes the database volume.

An existing `.env` with `FRONTEND_DATA_MODE=mock` stays in mock mode. Set it to
`api` and rerun the launcher; the build-argument fingerprint triggers the needed
frontend rebuild. No mock status should be read as evidence of a real download.

## Reproducing a missing-model first start

Stop the branch's AI container first. Resolve and inspect the exact
`models/pplx-embed-v2-late-0.6b` target, then remove only that model directory if
you intentionally want to force a fresh download. This is recoverable by
downloading again, but requires network access and time. Do not delete the
whole `models` parent, a Hugging Face-wide cache, the repository, source PDFs,
or the database volume. Then rerun `python scripts/start.py` and record
`GET /setup` through downloading, verifying, warming up and ready. Restart once
more to verify local reuse. The actual execution evidence belongs in the dated
C startup report; unit tests alone do not establish a real download/build.
