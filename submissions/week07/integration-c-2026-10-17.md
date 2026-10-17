# C Search Integration into the Canonical W7 Model

Date: 2026-10-17  
Branch: `w7-integration-bootstrap`

## Decision

C's search algorithms are now integrated without merging C's parallel
`source_files` / `source_versions` / `source_chunks` tables. B's
`source_chunks` remains the only text source. Search-only fields live in
`chunk_search_index`, keyed by `chunk_id` and backed by a cascading foreign
key.

## Implemented

- Added `chunk_search_index` with normalized text, search terms, optional
  384-dimensional embedding, model id and dimensions.
- Added migration `7f3a1b2c4d5e`, whose only parent is the existing head
  `445f908b73b4`.
- `persist_chunks` now synchronizes the derived keyword index after a chunk
  replacement. A changed chunk drops its old vector.
- `/search` reads only current, present, authorized canonical chunks.
- `/search` always provides keyword results; semantic/hybrid requests use
  vectors when available and return an explicit degradation reason otherwise.
- Added the AI service `/embeddings` boundary and the pinned local E5 adapter.
  A missing local model returns a safe degradation rather than breaking the
  keyword path.
- Added tests for index creation/rebuild and vector-backed semantic retrieval.

## Verified

| Check | Result |
| --- | --- |
| Python unit/integration suite | **136 passed, 1 skipped** |
| `ruff check .` | clean |
| Fresh PostgreSQL migration | reaches head `7f3a1b2c4d5e`; the later job-lease migration reaches `a1b2c3d4e5f6` |
| `chunk_search_index` rows in the live 16-file run | **20** |
| Live keyword queries K01-K05 | **5/5** expected file and page |
| Live evidence lookup after each keyword hit | **5/5** same chunk and page |
| Repeat scan | **0** new files or versions |
| Browser walkthrough | scan 19: 16/16 processed, 12 searchable, 4 unsupported; search and P1 evidence opened |
| Failed-job retry route | live job 20: `failed`/attempts 2 changed to `pending`/attempts 2; second retry returned 409 |
| Stale-claim recovery | live job 21: a simulated dead worker lease was reclaimed and completed at attempt 2; owner and lease cleared |

## Remaining limitations

- No local E5 model files are present in this checkout, so semantic search
  currently reports `semantic_not_integrated`/keyword fallback in the live
  browser. The model must be placed at `models/multilingual-e5-small` and the
  embeddings dependencies must be installed before semantic quality can be
  claimed.
- The worker now has bounded exponential backoff, lease expiry and stale-claim
  recovery. A failed job can also be explicitly requeued through
  `POST /jobs/{id}/retry`, and the browser exposes the same action. Load-testing
  multiple competing workers remains open.
- The formal report, README, 12-page deck, QA and release candidate are now in
  the repository. The recording and second-computer install record remain
  before the 24 October demonstration.
