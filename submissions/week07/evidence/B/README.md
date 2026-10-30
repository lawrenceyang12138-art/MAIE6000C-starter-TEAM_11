# B corpus, evidence and relation review

Reviewed on 2026-10-30. The original B checks were captured at
`develop@047b2ac8b6c584b366c3db8f211125a6b9febe4f`; the final integration
baseline is `develop@bbbddb9473594794ba342490b99ef7ab99dc6500`, including
Role A PR #7 and Role C PR #8.

The machine-readable review is
[`corpus-relations-review.json`](corpus-relations-review.json). It was generated
from temporary copies with a clean SQLite database, normal `handle_scan_root`,
`handle_extract_file`, and the assembled FastAPI evidence/relation routes. The
committed source files were not modified.

[`live-compose-results.json`](live-compose-results.json) records the separate
live PostgreSQL path through Compose API and Worker: 16 current files, the same
12/4 split, 12 direct evidence reads, and a temporary copied PDF whose changed,
restored and deleted states returned 409 `source_changed`, 200 and 404
`file_missing` without a rescan. The same live service automatically generated
person/project/topic relations for a temporary relation PDF, accepted all three
review decisions, retained three history rows, and returned 409
`review_conflict` for a stale revision.

## Final integration

The clean B branch was rebuilt on top of the final `develop` baseline. Its
combined Ruff/Python suite passes **587 tests**, including the PostgreSQL queue,
search and Alembic tests. Migration `20261030_0005` adds the C token and
physical-page sidecars to the single Alembic chain. D Node contracts pass
**55/55**, mock/fixture checks pass, and the frontend production build plus
Vitest **24/24** pass.

## Mounted team corpus

The mounted integration corpus contains 12 `basic_ready` PDFs and four
`unsupported` records. Every unsupported record has no chunk:

| relative path | status | error code |
| --- | --- | --- |
| `abnormal/corrupt.pdf` | `unsupported` | `corrupt` |
| `abnormal/encrypted.pdf` | `unsupported` | `encrypted` |
| `abnormal/no_text_layer.pdf` | `unsupported` | `no_text_layer` |
| `regression/unsupported.txt` | `unsupported` | `unsupported_format` |

The 12 normal PDFs are `regression/group-a/doc01.pdf` through `doc06.pdf` and
`regression/group-b/doc07.pdf` through `doc12.pdf`. Their stored page numbers and
text match the `MarkerNNPp` content in each PDF. Exact page snippets and hashes
are in `corpus.records` in the JSON artifact.

## D proposal fixture review

The separate `fixtures/normal`, `fixtures/abnormal`, and `fixtures/unsupported`
proposal also parses as 12 `basic_ready` plus four `unsupported`, but its current
manifest does not match the parser contract:

- `empty.pdf` is `unsupported/unsupported_format`, not `failed/EMPTY_FILE`.
- `truncated.pdf` is `unsupported/corrupt`, not `failed/TRUNCATED_PDF`.
- `corrupt.pdf` is `unsupported/unsupported_format`, not
  `failed/CORRUPT_PDF`.
- `team11-unsupported-notes.docx` is correctly a handled `unsupported`, but its
  persisted code is lowercase `unsupported_format`, not the uppercase manifest
  spelling.

The mismatch list is under `d_proposal_corpus.manifest_mismatches`. D owns the
next unified freeze/version. These findings came from direct source parsing, not
from retrieval evaluation, and expected search answers were not changed.

`python scripts/validate_d_gold.py` independently passed its source-location
checks: 10/10 query pages and 16/16 corpus hashes matched, with retrieval
evaluation not run. That validator does not decide parser outcome status or
stable reason codes, which is why the direct-scan mismatches above still need a
D-owned freeze update.

## Relation handoff to D

The clean-scan sample is `tests/fixtures/relations/entities.pdf`. It produces one
`person`, one `project`, and one `topic` candidate. `relation_sample` in the JSON
contains the exact HTTP response, every returned `chunk_id`, and the matching
evidence response.

For each relation with `evidence_missing=false`:

1. Use `relation.chunk_id` directly as `GET /evidence/{chunk_id}`.
2. Require the evidence `version_id`, `chunk_id`, file, page and quote to match
   the selected relation.
3. Enable review. Confirm/reject omit `corrected_entity_id`; corrected requires
   an existing replacement entity.
4. Send the displayed `decision_revision` as `expected_revision`.
5. Expect HTTP 200 with `{relationship_id, decision, decision_revision}`.

If `chunk_id` is null or `evidence_missing=true`, hide the quote and keep review
disabled. A `409 review_conflict` requires a fresh relation read.
