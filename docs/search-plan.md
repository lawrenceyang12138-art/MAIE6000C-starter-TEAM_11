# Search, local embeddings, and evaluation

The 2026-10-29 [team PDF evaluation and recovery guide](search-team-pdf-evaluation.md)
adds the frozen D-gold adapter, real scan/parse/index runner, actual-source checks,
model checksum validation and backfill instructions. Its dated results are
separate from the historical hand-authored chunk benchmark below. B review and
team semantic-threshold approval remain pending.

Updated: 2026-10-18 for the canonical C branch. Initial standalone model and
evaluation evidence was recorded on 2026-10-15. The
[integration handoff](search-integration-handoff.md) describes the current
boundaries, and the [schema adaptation record](search-contract-differences.md)
explains how C now uses B's file, version, and chunk tables.

## Implementation

- `services/search/text.py`: NFKC normalization, English words, and contiguous CJK
  bigrams. Tokens do not cross punctuation boundaries.
- `services/search/retrieval.py`: PostgreSQL full-text search, exact pgvector
  cosine retrieval, weighted hybrid ranking, and one result per file.
- `services/search/embeddings.py`: pinned local multilingual E5 and an internal
  HTTP backend, with explicit vector validation.
- `services/search/indexing.py`: canonical fixture import and version indexing;
  batches contain at most 16 passages and vectors are published after all pass.
- `services/search/evaluation.py`: frozen-answer evaluation requiring both the
  correct file and source page. Degraded semantic responses do not count as
  semantic successes.
- `scripts/search_tools.py`: explicit model preparation, migrations, synthetic
  fixture import, indexing, and evaluation.

A owns scanning, source authorization, and job dispatch; B supplies parsed text
and evidence; D consumes the API. The fixture importer uses hand-authored chunks
and does not perform scanning or PDF extraction.

## Local model

The model is `intfloat/multilingual-e5-small`, pinned to revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`. Its full model identifier joins those
values with `@`; vectors have 384 dimensions. Inference uses E5's `query: ` and
`passage: ` prefixes, attention-mask mean pooling, and L2 normalization. CPU
inference defaults to four threads.

Preparation downloads the pinned safetensors/tokenizer files and writes their
SHA-256 manifest. Runtime checks that manifest and uses `local_files_only=True`
and `trust_remote_code=False`. The explicit `download-model` command is the
networked preparation step. Search and indexing use local files or the internal
AI service. Model weights remain in ignored `models/multilingual-e5-small/` and
must be copied separately to a backup computer under the model's license.

Warm the internal `/embeddings` endpoint before a demonstration: first-load
checksum verification and model initialization can otherwise exceed the search
API's ten-second timeout and trigger keyword fallback.

```json
{"texts": ["Database backup instructions"], "kind": "passage"}
```

The internal response contains `model`, `dimensions`, and `vectors`. Requests
contain 1-16 passages of 1-2000 characters. The tokenizer truncates at 512 tokens.
Indexing embeds at most the first 2000 characters of an existing long chunk while
retaining its source text for keyword search. Queries contain at most 500
characters and 64 distinct searchable tokens. Vectors must contain 384 finite
numbers with an L2 norm between 0.99 and 1.01.

## Canonical persistence and eligibility

`files`, `file_versions`, and `source_chunks` are the authoritative source tables.
The one-to-one `chunk_search_index` sidecar contains normalized keyword fields,
the nullable vector, and its model metadata. Its `chunk_id` references the same
source chunk used by evidence and relations. SQLite stores vectors as JSON for
unit tests; PostgreSQL uses `vector(384)`.

PostgreSQL indexes `to_tsvector('simple', search_terms)` with GIN. English matches
whole tokens and CJK text uses contiguous bigrams, so no additional database
tokenizer is required. Vector retrieval uses exact cosine distance through `<=>`;
the small demonstration corpus does not establish large-scale performance.

Search accepts `active` or `paused` roots, present files, and the file's current
version in `basic_ready` or `enriched`. Root and file filters further restrict the
query. Search returns relative display paths and stored text; source opening and
on-disk verification use the authorized evidence path.

Keyword sidecars must exist before a chunk can be searched. `embed_version()`
creates them before embedding, including when AI later fails. SQL/COPY operations
that bypass ORM processing must explicitly generate matching `search_text` and
`search_terms` values. The caller owns transaction completion and job retries.

## Ranking and response

`keyword` requires no AI request. `semantic` selects vector candidates; `hybrid`
combines both channels. The keyword score is distinct-token coverage times 0.8,
plus 0.2 for a complete phrase and 0.25 for a filename match, capped at 1. Semantic
scores use the nonnegative part of cosine similarity. Hybrid ranking defaults to
keyword weight 0.65 and semantic weight 0.35, normalized by their sum. There is no
separate cross-encoder reranker.

Each channel chooses the best chunk per file before selecting up to 200 candidate
files. Final results contain one evidence chunk per file. `top_k` defaults to 10
and is limited to 50. `total` counts distinct files in this bounded candidate
pool; it is not an unbounded corpus hit count. Ties use source order and stable
IDs. Canonical response fields include `root_id`, `file_id`, `version_id`,
`version_created_at`, `chunk_id`, `ordinal`, and nullable `page`.

## Degradation and failure isolation

| Condition | Reported reason |
| --- | --- |
| Embeddings disabled | `ai_disabled` |
| AI unavailable or returning 503 | `ai_unavailable` |
| Internal request timeout | `ai_timeout` |
| Model or dimensions mismatch | `embedding_model_mismatch` |
| Malformed vector response | `invalid_embedding_response` |
| No compatible stored vectors | `embeddings_not_ready` |
| Some eligible chunks lack compatible vectors | `partial_embeddings` |

Unavailable semantic retrieval switches `effective_mode` to `keyword`, returns
HTTP 200, and reports `degraded=true` plus its reason. Partial vectors retain the
requested semantic/hybrid mode and report `partial_embeddings`: semantic results
contain embedded files, while hybrid can also retain keyword matches. Any
degraded semantic response fails semantic evaluation.

A malformed local model manifest returns the safe `local_model_unusable` reason;
the AI service returns 503 and the HTTP search backend follows keyword fallback.
Database failures remain errors. Failed embedding batches leave source text and
existing vectors available, with `IndexResult.embedding_error` for the caller.

## Frozen evaluation evidence

`fixtures/search/` contains 12 synthetic documents, 15 page-located chunks, five
keyword queries, and five semantic queries. Answers were frozen before the first
E5 run. Keyword success requires the correct file and page at Top-1; semantic
success requires both within Top-3. The semantic target is four of five queries.

The historical run achieved keyword 5/5 and semantic 4/5 with no duplicate files.
`sem-2` returned the correct account manual but selected page 3 instead of page 1,
so it remains a failure. These small synthetic results do not establish quality
on team PDFs or acceptance of the complete product.

Committed fixture and evidence JSON now uses ASCII Unicode escapes. Decoding
produces the same bilingual values. Historical reports retain their original
byte hashes; [fixture-encoding.json](../submissions/week07/evidence/C/fixture-encoding.json)
maps the original Git bytes to the escaped representation and records an
encoding-independent canonical JSON hash.

## Windows CMD verification

Run from the repository root with Python 3.11, as required by `pyproject.toml`.
Use a compatible environment if Anaconda base has another Python version.

```cmd
python -m pip install -e ".[dev,embeddings]"
python -m scripts.search_tools download-model
python -m scripts.search_tools migrate
python -m scripts.search_tools seed
python -m scripts.search_tools evaluate
python -m scripts.verify_search_local
python -m scripts.verify_search_http
python -m pytest -q tests/unit tests/integration -m "not postgres"
python -m ruff check .
```

`download-model` requires network access during preparation. Existing verified
model files can be reused for subsequent offline runs. Prepare `.env` without
overwriting an existing file, then start Compose:

```cmd
python -c "from pathlib import Path; p=Path('.env'); p.write_bytes(Path('.env.example').read_bytes()) if not p.exists() else None"
python -c "import subprocess; subprocess.run(['docker','compose','up','--build'],check=True)"
```

Compose uses `pgvector/pgvector:pg16`, a PostgreSQL host port of 15432 by default,
read-only source mounts, and a read-only local model mount. For isolated database
checks, pass the URL of a disposable PostgreSQL/pgvector database:

```cmd
python -m scripts.verify_search_http --database-url postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_verify --pytest-output work/pytest-all.xml
python -c "import os,pytest; os.environ['SEARCH_TEST_DATABASE_URL']='postgresql+psycopg://postgres:postgres@127.0.0.1:55432/team11_c_verify'; raise SystemExit(pytest.main(['-q','tests/unit','tests/integration']))"
```

The HTTP verification runner starts temporary API, AI, and worker processes on
available loopback ports and stops them when finished. Historical full-suite
reports describe the source and test count at their recorded date. Count current
passes and skips from the new run, including a live HTTP smoke test and real
PostgreSQL tests, before making a new integrated acceptance claim.
