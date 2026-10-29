# M1 catalogue: three scan scenarios

Date: 2026-10-21 (Asia/Hong_Kong)
Code: commit `64ad2ed` (branch `Role_A`)
Environment: Docker Compose stack built from that commit; Windows 11 host;
client Python 3.11.17.

The M1 gate asks for three scenarios seen through the real stack: a first
import, a repeated scan, and a scan that mixes abnormal files into a healthy
corpus. Each row below is an observed number, not an expectation.

## Scenario 1 - first import

Fresh root `bec3ef8d-8803-4b87-bd23-738ca36c354c`, mount `corpus`, path
`regression` (12 normal PDFs across two subfolders plus one unsupported file).

| Measure | Value |
| --- | --- |
| scan job | 34, `completed` |
| files | 13 |
| `basic_ready` | 12 |
| `unsupported` | 1 (`regression/unsupported.txt`, reason `unsupported_format`) |
| `failed` | 0 |
| `discovered` / `extracting` left over | 0 / 0 (settled within the polling window) |
| `embed_file` jobs | 12 `completed` |
| presence | 13 `present` |

Job tally for this root, from `jobs` grouped by type and status:

```text
embed_file   | completed | 12
extract_file | completed | 13
scan_root    | completed |  2
```

Thirteen files produced exactly thirteen extraction jobs and twelve index jobs
(only `basic_ready` versions are indexed), which is the one-to-one dispatch the
contract asks for - no duplicate, no missing.

All twelve normal PDFs became `basic_ready`; the unsupported file stayed visible
as a record with a reason instead of being dropped.

## Scenario 2 - repeated scan

Same root, rescanned immediately after the first run.

| Measure | Value |
| --- | --- |
| rescan job | 60, `completed` |
| new file rows | 0 |
| `file_counts` changed | no |
| duplicate versions or jobs | none (see `scan-idempotency.md` for the totals) |

## Scenario 3 - abnormal files mixed into a healthy corpus

Whole mount, root `ecb84a43-31e2-40a0-8b3c-38687d56541b` (16 files: 12 normal,
1 unsupported, 3 damaged/encrypted/image-only PDFs).

| Measure | Value |
| --- | --- |
| files | 16 |
| `basic_ready` | 12 |
| `unsupported` | 4 |
| `failed` | 0 |
| exceptional files | `abnormal/corrupt.pdf` (`corrupt`), `abnormal/encrypted.pdf` (`encrypted`), `abnormal/no_text_layer.pdf` (`no_text_layer`), `regression/unsupported.txt` (`unsupported_format`) |

The four bad inputs did not stop the twelve good ones: every normal PDF was
`basic_ready` in the same scan, and each bad input carries a specific reason
code rather than a generic failure.

## Job states observed

Across both roots every job reached `completed`; none is `failed`, `pending` or
`claimed` at rest. This matters for the state contract: a damaged document is a
*recorded outcome on the version* (`unsupported` + reason code), not a failed
job (contract 3.4). A job only fails on an error that is not a property of the
document - and that did not occur here.

## Reproduce

```bash
docker compose up -d --build

# Scenario 1 + 2
python scripts/w7_evidence_probe.py --path regression \
  --out submissions/week07/evidence/scan-run-first-import.json

# Scenario 3
python scripts/w7_evidence_probe.py \
  --out submissions/week07/evidence/scan-run.json
```

Both runs also hash the host copy of the corpus before and after: 18 files
checked, 0 changed, 0 missing.

## Limits

- The compose mount is read-only, so "edit one file" and "revert it" cannot be
  exercised here. Those cases are unit-level and listed in
  `scan-idempotency.md`.
- Scenario 3's root already existed from the earlier PR #3 run, so its job ids
  start high; the counts are current-state, not a from-empty import. Scenario 1
  is the from-empty case.
- Version and job totals come from manual `psql` queries, because the API does
  not expose them by design.
