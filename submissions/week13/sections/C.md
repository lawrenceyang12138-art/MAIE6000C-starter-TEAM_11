# Week 13 contribution: Role C search and local AI

**Status:** implementation and the validation below are complete on the tested
snapshot; this is a Role C contribution, not a team sign-off or release tag.
**Run date:** 2026-11-23. The production runtime was GitHub `develop` at
`5eb12cff3f0eaac0b5b0f4ca1b75524e052de06f`. The new evaluation and reporting do
not change production retrieval, Worker behavior, API fields or schema.

## How search is delivered

The API restricts retrieval to current versions of authorized sources. The
Worker produces keyword indexes before model availability is required and
uses the normal durable queue to recover missing token matrices once AI is
ready. PPLX `pplx-embed-v2-late-0.6b` is pinned at
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`, locally verified and run on CPU.
It supplies 128-dimensional token vectors and exact token MaxSim scoring;
hybrid uses the existing 0.65 keyword / 0.35 semantic weights. The runtime
returns one evidence chunk per file. Requested and effective search modes
remain distinct, and model failures explicitly fall back to keyword when
available. Search evidence resolves to the same source identity and passage.

## Functional and reliability evidence

- The older W7 fixture workflow passed **202/202 HTTP/DB checks** on the newer
  `develop` runtime with AI stopped, including scan, keyword, source, rescan
  and review. This is not a rerun of the full historical browser acceptance.
- On the new 28-file fixture root, the real Worker produced 54 keyword indexes
  and 24 PDF metadata rows before AI was present, with zero token matrices.
  Keyword and fallback evidence agreed with the frozen source. Semantic and
  hybrid identified their fallback as `ai_unavailable`, not model success.
- After starting the pinned AI service, the ordinary Worker recovered **54/54
  compatible token matrices** (2,397 token vectors), promoted the 24 readable
  versions to `enriched`, and kept the same files, versions and chunk IDs. The
  four unsupported outcomes and all source hashes remained unchanged. The
  marker probe returned the verified passage at rank 1 in all three modes.
- After indexing, stopping AI again and force-recreating PostgreSQL, API and
  Worker with the same volume preserved source identities, index counts and
  keyword access. When AI returned, semantic/hybrid returned the verified
  passage without a manual re-index. This was on the same machine, not backup
  machine or browser acceptance. See the [restart procedure](../../../docs/search-validation.md#verify-persistence-across-container-recreation)
  to repeat the persistence checks.
- On Linux/Python 3.11 and real PostgreSQL with Alembic applied, Ruff passed
  and the Python suite recorded **835 passed, 3 skipped**. The skips were
  Windows-only shell/bridge checks; the new 10 focused tests also passed on
  the Windows host. The old D freeze still passed 16 file hashes and 10 source
  locations. An initial ad-hoc full test run omitted the Alembic prerequisite
  and had 8 setup errors from the missing `vector` extension. The clean CI-
  equivalent rerun applied migrations first and had no errors.

## Topical retrieval, with navigation disabled

The [candidate v1 freeze](../../../fixtures/search/w13-v1/README.md) uses exact
shared source paths and SHA-256 values. The 12 topical queries (six English,
six Chinese) were frozen before retrieval and give no filenames or page hints.
The documents are synthetic and English; this measures Chinese-query-to-English-
source performance, not the breadth of Chinese-source collection support.

| Mode | Relevant file Top-3 | Correct physical page Top-3 | Verified supporting passage Top-3 |
| --- | ---: | ---: | ---: |
| Keyword | 5/12 | 2/12 | 2/12 |
| Semantic (PPLX) | 12/12 | 11/12 | 11/12 |
| Hybrid | 12/12 | 11/12 | 11/12 |

The five exact-marker keyword controls were **5/5 Top-1** for file, page and
passage. Semantic and hybrid passage hits were **5/6 English and 6/6 Chinese**.
`T01` located `topics/north/atlas.pdf` but selected page 1 (routine retention)
instead of page 2 (offsite restoration drill). It was rank 1 for semantic and
rank 2 for hybrid. This source-selection miss remains a miss; word weights,
answers, and page navigation were not adjusted to make the score pass. The old
W7 model-only and navigation-assisted results keep their original denominator
and are not pooled with this run.

## Performance and reproduction

The same Windows 11 / Intel Core Ultra 9 275HX host used Docker Desktop Linux
containers, PostgreSQL 16.15, pgvector 0.8.7, Alembic `20261119_0007`, Torch
2.8.0 CPU, and four embedding threads. Measurements use one serial loopback
HTTP client; 24 timed requests per mode, excluding a separate first warm-model
probe and evidence reads. The larger root repeats documents only for load
measurement. It is **not** a second quality dataset. Times are milliseconds.

| Files / chunks | Keyword median / p95 | Semantic median / p95 | Hybrid median / p95 |
| --- | ---: | ---: | ---: |
| 28 / 54 | 9.32 / 10.54 | 177.01 / 215.61 | 176.30 / 187.97 |
| 112 / 222 | 18.03 / 23.87 | 788.05 / 890.05 | 762.34 / 836.33 |

A fresh 112-file import, parse and index took **88.58 s** with the model warm
and produced 222 matrices (13,072 token vectors). Over 34 `docker stats`
samples during the load run, the sampled memory peaks were about 199 MiB API,
93 MiB Worker, 708 MiB AI and 70 MiB PostgreSQL. These are cache-adjusted Docker
samples, not exact peak process memory. The test does not establish throughput
for concurrent clients or latency on a large, diverse collection. Exact MaxSim
reads token matrices; the project does not claim an ANN index for that path.

Reproduce with the [validation runbook](../../../docs/search-validation.md).
The [compact result](C-validation.json) records execution identities, exact
verifier commands and separate denominators. Raw local reports are not committed.

## Remaining human decisions and limitations

B still needs to review the sources, physical pages and acceptable alternatives.
D and the team still need to agree whether to use this candidate and what an
acceptance threshold would be. No approval is inferred from automated quote or
hash checks; any new reviewed dataset should use a separate freeze version.
Independent query authorship, a broader corpus, backup-device reproduction and
reviewer acceptance remain unverified. Final team artifact assembly, demo and
sign-off are outside this Role C contribution.

Codex assisted implementation, fixture drafting, test execution and this brief.
The evidence above comes from actual commands and measured results. This does
not constitute a personal declaration or approval on behalf of another member.
