# Real E5 Semantic Verification — 2026-10-17

Branch: `w7-integration-bootstrap`

## Model

- Model: `intfloat/multilingual-e5-small`
- Revision: `614241f622f53c4eeff9890bdc4f31cfecc418b3`
- Local directory: `models/multilingual-e5-small`
- Model cache size: about 486 MB
- `/embeddings` returned 384-dimensional vectors with L2 norm approximately 1.0.

The model directory is intentionally not committed to Git. It is copied into
the demo/release bundle separately.

## Index

- 12 current normal versions were embedded.
- 20 canonical chunks received vectors.
- Embedding errors: 0.

## Frozen semantic queries

The five semantic descriptions from `tests/fixtures/w7-gold-queries.json` were
run in `semantic` mode with Top-3 results:

| Query | Expected file and page | Top-3 result | Evidence |
| --- | --- | --- | --- |
| S01 | `team11-demo-09.pdf` page 2 | matched | same chunk/page |
| S02 | `team11-demo-10.pdf` page 3 | matched | same chunk/page |
| S03 | `team11-demo-11.pdf` page 1 | matched | same chunk/page |
| S04 | `team11-demo-12.pdf` page 2 | matched | same chunk/page |
| S05 | `team11-demo-06.pdf` page 1 | matched | same chunk/page |

Result: **5/5 Top-3 file/page hits** and **5/5 evidence matches**.

The query-intent layer also recognizes generic document numbers and
first/middle/last page hints in English and Chinese. It is a deterministic
re-ranking aid, not a separate model-quality claim.

## Fallback

The existing degradation path remains: if the model or AI service is
unavailable, search returns keyword results with an explicit reason and never
labels them as semantic success.
