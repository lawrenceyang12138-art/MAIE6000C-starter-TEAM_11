# Role C search validation

This runbook measures the current retrieval implementation through HTTP and an
actual Worker and PostgreSQL. It does not alter ranking, run a mock AI backend,
change the default Compose deployment, or approve the benchmark. These tools
use a dedicated Compose project, synthetic input and a separate database. Do
not use the suite against an existing application database or user files.
See the [dated results](#2026-11-23-validation-results) for the recorded run
and its limits.

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

## 2026-11-23 validation results

These results are Role C evidence, not team acceptance or a release tag. The
application snapshot was `develop` at `5eb12cff3f0eaac0b5b0f4ca1b75524e052de06f`,
with the pinned PPLX model described in the [search guide](search-plan.md). The
[machine-readable record](../submissions/week13/sections/C-validation.json)
retains runtime identifiers, commands, and denominators. Raw reports remain
local under `work/c-search-validation-reports/baseline-5eb12cf/`.

### Functionality and recovery

- With the AI service stopped, the W7 fixture workflow passed **202/202 HTTP/DB
  checks** for scan, keyword search, evidence, rescan, and review. This was not
  a rerun of the W7 browser acceptance checks.
- On the separate 28-file W13 root, the Worker created 54 keyword indexes and
  24 PDF metadata rows with no token matrices. Keyword and fallback evidence
  matched the frozen source. Semantic and hybrid requests reported
  `ai_unavailable`; these were not model successes.
- After AI started, the normal Worker recovered **54/54 compatible token
  matrices** (2,397 token vectors) and enriched 24 readable versions without
  changing file, version, or chunk IDs. The four unsupported outcomes and
  source hashes were unchanged. The marker probe found the verified passage
  at rank 1 in all three modes.
- Recreating PostgreSQL, API, and Worker with the same volume while AI was off
  preserved identities, index counts, and keyword access. With AI restored,
  semantic and hybrid found the verified passage without manual re-indexing.
  This was a [same-machine restart check](#verify-persistence-across-container-recreation),
  not backup-device or browser acceptance.
- With Alembic applied on Linux/Python 3.11 and real PostgreSQL, Ruff passed and
  the Python suite recorded **835 passed, 3 skipped** (Windows-only checks).
  Ten focused tests passed on Windows. The historical D freeze matched 16 file
  hashes and 10 source locations. An initial run without migrations had eight
  setup errors due to the missing `vector` extension; the migrated rerun had none.

### Topical retrieval and limits

Navigation was disabled. The [candidate corpus](../fixtures/search/w13-v1/README.md)
uses synthetic English sources with both English and Chinese queries. It does
not measure coverage of Chinese-language sources.

| Mode | Relevant file Top-3 | Correct physical page Top-3 | Verified passage Top-3 |
| --- | ---: | ---: | ---: |
| Keyword | 5/12 | 2/12 | 2/12 |
| Semantic (PPLX) | 12/12 | 11/12 | 11/12 |
| Hybrid | 12/12 | 11/12 | 11/12 |

The five exact-marker keyword controls were **5/5 Top-1** for file, page, and
passage. Semantic and hybrid each had passage hits for 5/6 English and 6/6
Chinese queries. For `T01`, both chose page 1 (routine retention) of
`topics/north/atlas.pdf` instead of page 2 (offsite restoration drill). That file
ranked first for semantic and second for hybrid; it remains a page and passage
miss. These results are not pooled with W7 model-only or navigation-assisted runs.

B's source-label review and team agreement on the candidate and threshold are
pending. Independent query authorship, coverage of a broader corpus,
backup-device reproduction, and final team sign-off remain unverified.

### Performance

The run used Windows 11 on an Intel Core Ultra 9 275HX, Docker Desktop Linux
containers, Torch 2.8.0 CPU, and four embedding threads. Timings are in
milliseconds from one serial loopback client with a warm model: 24 timed
requests per mode, excluding the first measured probe and evidence reads.

| Files / chunks | Keyword median / p95 | Semantic median / p95 | Hybrid median / p95 |
| --- | ---: | ---: | ---: |
| 28 / 54 | 9.32 / 10.54 | 177.01 / 215.61 | 176.30 / 187.97 |
| 112 / 222 | 18.03 / 23.87 | 788.05 / 890.05 | 762.34 / 836.33 |

The warm-model 112-file import, parse, and index took **88.58 s** and produced
222 matrices (13,072 token vectors). Across 34 `docker stats` samples, the
sampled peaks were about 199 MiB API, 93 MiB Worker, 708 MiB AI, and 70 MiB
PostgreSQL. These are cache-adjusted container samples, not peak process RSS.
The larger root repeats files for load testing; it is not a second quality
corpus. This run does not establish throughput for concurrent clients or
latency on a large, diverse corpus. Retrieval uses exact token MaxSim, not ANN.

## Role C development record

The results above come from executed checks and measurements and cover Role C only.
