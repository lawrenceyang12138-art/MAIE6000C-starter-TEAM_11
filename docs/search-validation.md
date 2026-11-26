# Role C search validation

This runbook measures the current retrieval implementation through HTTP and an
actual Worker and PostgreSQL. It does not alter ranking, run a mock AI backend,
change the default Compose deployment, or approve the benchmark. These tools
use a dedicated Compose project, synthetic input and a separate database. Do
not use the suite against an existing application database or user files.

## Inputs and quality protocol

- [Frozen candidate v1](../fixtures/search/w13-v1/README.md): 28 files, including
  the exact 16 W7 Compose fixtures and 12 small topical PDFs. A separate `load`
  root adds copies at new paths. It is never included in quality denominators.
- `check` verifies the manifest and answer hashes, actual file bytes, physical
  page counts, and all reference excerpts with PyMuPDF independently of the
  application's parser. The verifier requires a chunk on every physical page
  of each ready fixture version, including pages not cited by any query, and
  repeats byte checks after the run.
- The five W7 marker checks measure keyword Top-1 exact source location. The 12
  topical prompts (six English and six Chinese, six subjects) each run keyword,
  semantic, and hybrid Top-3 against the same corpus, with navigation disabled.
  The topical queries do not disclose a filename, ordinal or physical page.
- File, physical page, and supporting passage are different metrics. File hits
  require the correct current file. Page hits additionally require the expected
  physical page. Passage hits require the frozen quote in the rendered evidence
  chunk on that page. Every result in the quality run is checked against the
  evidence API for file/version/chunk/page/text/hash agreement, and duplicate or
  out-of-scope results are integrity failures. Degraded model responses are not
  semantic hits. The reports retain misses and their returned file/page ranks.
- B's source-label review and D's corpus agreement are pending. For review, use
  the frozen query IDs, verify every expected quote and physical page from the
  original file, and note any other defensible location. Agree separately on a
  team threshold if one is needed. Do not edit v1 or the old W7 answers after
  observing scores; changed inputs require a new version and actual approval.

## Reproduce on an isolated stack

Use a **Python 3.11** environment, Docker Desktop or Docker Engine with Compose
v2, and a few gigabytes for the image and model. Install the host validation
tools from the repository root. The code block can be run from Windows CMD.

```cmd
python -m pip install -e ".[dev]"
python -m scripts.c_search_suite check
python -m scripts.c_search_suite stage --corpus quality
python -m scripts.c_search_suite stage --corpus load --load-copies 7
```

Prepare the [pinned model cache](model-startup.md) before the AI phase. Existing
verified files can be reused. For a cold download without deploying the product
stack, the same startup preparer can be invoked explicitly from the host:

```cmd
python -c "from pathlib import Path; from threading import Event; from services.search.model_preparation import prepare_local_model; from services.search.text import MODEL_DIRECTORY; prepare_local_model(Path(MODEL_DIRECTORY), progress=lambda **p: print(p['state']) if 'state' in p else None, cancel=Event(), timeout=60)"
```

Use a fresh validation project/volume and ensure local ports `15485`, `18085`,
and `18185` are free. The API and Worker mount only the staged inputs read-only;
AI uses the locally verified cache and cannot download in this Compose file.
The verifier never writes to PostgreSQL directly; it authorizes one fixture
root through HTTP for each import. No production `.env` is mounted.

```cmd
docker compose -f compose.search-validation.yaml build api
docker compose -f compose.search-validation.yaml up -d db api worker
```

Wait for `http://127.0.0.1:18085/health/ready` to return 200 after migrations.
Keep `ai` stopped for `prepare`. `finish` takes the successful `prepare` report
for the same run ID and root and waits for ordinary Worker recovery; there is
no manual re-index or database mutation by the verifier. `load` measures a
fresh root with the model already warm. Use the same copy count in stage/load.

```cmd
python -m scripts.verify_c_search prepare --run-id w13-local
docker compose -f compose.search-validation.yaml up -d ai
python -m scripts.verify_c_search finish --run-id w13-local
python -m scripts.verify_c_search load --run-id w13-local --load-copies 7
```

Raw JSON and its execution parameters and code fingerprints stay under ignored
`work/c-search-validation-reports/`. Reports are not overwritten. To repeat a
fresh import, stop the scoped test project and use a different `-p` project name
and `--run-id`; a new project has a separate volume. To collect comparable memory
samples, use `docker stats --no-stream` against only the validation containers
before and during load. Report sampled peak (not exact peak RSS), hardware, CPU
threads, corpus, model revision and sample count. `first_measured_ms` is the
first timed request on a **warm model**, not a cold boot. API timings measure a
serial loopback client and exclude evidence readback. The reported database
size is the whole isolated database, not only the just-measured root.

### Verify persistence across container recreation

Start with a successful `finish` from the current verifier. Use the **same**
Compose project, ports, staged corpus, run ID, and named `search_validation_db`
volume for all steps below. If you supplied `-p`, include it on every Compose
command. Do not remove the volume, rerun `prepare`, or trigger a rescan.

Stop only AI and capture a baseline with keyword and AI-unavailable fallback:

```cmd
docker compose -f compose.search-validation.yaml stop ai
python -m scripts.verify_c_search probe --run-id w13-local --probe-stage before
docker compose -f compose.search-validation.yaml ps -q db api worker
```

Force-recreate PostgreSQL, API, and Worker, leaving AI stopped and their
existing volume in place. Confirm that all three container IDs changed:

```cmd
docker compose -f compose.search-validation.yaml up -d --no-build --force-recreate db api worker
docker compose -f compose.search-validation.yaml ps -q db api worker
```

Once `/health/ready` on the validation API returns 200 again, check the
same offline searches, then start AI and verify search after model readiness:

```cmd
python -m scripts.verify_c_search probe --run-id w13-local --probe-stage after
docker compose -f compose.search-validation.yaml up -d --no-build ai
python -m scripts.verify_c_search probe --run-id w13-local --probe-stage restored
```

All three commands must pass. Each compares source IDs and counts (including
keyword and token indexes) with `finish.json`. `after` compares effective modes,
fallback reasons, and ranked marker evidence with `before`; `restored` compares
the same fields with `finish`, including semantic and hybrid without fallback.
The read-only probes record results in `probe-before.json`, `probe-after.json`,
and `probe-restored.json` alongside the first reports, without re-indexing.

### Clean up

The normal application stack is not needed. When finished, `docker compose -f
compose.search-validation.yaml down` stops only the default validation project
and preserves its volume. If you used `-p`, use the same project name when
stopping it. The model cache and local reports are reusable and are not tracked.

See the [C technical brief](../submissions/week13/sections/C.md) for the dated
run, gaps, and interpretation.
