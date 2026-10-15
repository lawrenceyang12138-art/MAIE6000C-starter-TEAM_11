# B - PDF parsing baseline (10.14 AM)

Owner: B (read files / PDF parsing and evidence quality)
Scope: establish a per-page text extraction baseline that keeps the original
page number and the file identity. This is the first step of the "read files"
workstream; chunking and write-back come next.

## What was built

- `services/parsing/pdf.py` - `extract_document(path)` returns a document with
  its `content_sha256`, `byte_size`, `page_count`, and one `PageText` per page
  carrying the **1-based page number a reader sees in a PDF viewer**.
- `services/parsing/__init__.py` - package entry point.

The module treats unreadable input as a normal outcome: `UnsupportedDocument`
carries a stable `reason_code` that the caller records against the file
version, so one bad file cannot stop a scan.

## Normal documents: real extraction samples

Run inside the API container against three real course PDFs, each mounted
read-only. Command:

```
docker compose run --rm --no-deps \
  -v "/path/to/samples:/fixtures:ro" api \
  python -c "from services.parsing.pdf import extract_document; ..."
```

Observed output (abridged to the first three pages per file):

| File | sha256 (first 12) | Bytes | Pages | Page 1 begins | Page 2 begins | Page 3 begins |
| --- | --- | --- | --- | --- | --- | --- |
| Week 1 - Lab.pdf | `10f16938771d` | 1,569,560 | 28 | MAIE 6000C: Engineering AI Products... | Session 1 - Setup, GitHub, Docker... | Welcome and Lab Goal... |
| Week 4 - Data Persistence and Schema Design.pdf | `89fec97aaf80` | 1,045,638 | 23 | MAIE 6000C: Engineering AI Products... | Today's focus - Persistent entities... | Today's Learning Goals... |
| Week 5 - Lab.pdf | `c4341d1da7ac` | 850,050 | 22 | MAIE 6000C: Engineering AI Products... | Today's Rule: Observe the Contract... | Session 1 Plan and Team Roles... |

Per-page character counts on the sampled pages ranged from 222 to 501
characters. Page numbering starts at 1 and follows document order.

## Abnormal documents: three distinct reasons

Three synthetic fixtures (see `tests/fixtures/parsing/`) were each rejected with
a different reason code:

| Fixture | Observed outcome |
| --- | --- |
| `encrypted.pdf` | rejected, `reason_code = encrypted` |
| `corrupt.pdf` | rejected, `reason_code = corrupt` |
| `no_text_layer.pdf` | rejected, `reason_code = no_text_layer` |

A PDF that opens but yields no text at all is reported as `no_text_layer`
rather than "0 chunks", because an empty result would be indistinguishable from
an empty document.

## Automated verification

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_pdf.py
```

Result: **6 passed**. The tests assert page-number preservation, file identity
(sha256 and byte size), the three abnormal reason codes, and that parsing does
not modify the source file - the last one is the "originals unchanged"
acceptance criterion in miniature.

Full suite at this commit: **12 passed, 1 skipped**. `ruff check .` clean.

## Not done yet (explicitly out of this step)

- Chunking with overlap and cross-page handling (next).
- Writing `source_chunks` rows against a real file version (next).
- Running the parser from the worker dispatch loop - that is A's boundary, and
  this module is not wired into the worker yet.
- No claim is made about OCR or scanned PDFs; only text-layer PDFs are in scope.
