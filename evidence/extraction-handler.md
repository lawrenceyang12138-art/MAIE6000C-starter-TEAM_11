# B - Extraction handler and failure isolation (10.16)

Owner: B (read files / PDF parsing and evidence quality)
Module: `services/parsing/handler.py`

## The seam with A's worker

The worker owns the dispatch loop; this handler owns what happens to one
version. The worker calls:

```
handle_extract_file(db, version_id, source_path) -> resulting status
```

Inside, the handler runs `extract_document` then `chunk_document` then
`persist_chunks`, and records the outcome on the version row.

## Three rules

1. **A bad document must not raise.** Encrypted, damaged and image-only files
   are ordinary results. They are recorded against the version and returned
   normally, so the worker continues with the next file instead of the whole
   scan stopping at the first problem.
2. **A file that changed while being read must not be published.** Extraction
   returns a hash of what was actually read. If it differs from the hash the
   version was created with, the chunks are discarded rather than attached to a
   version that claims different bytes.
3. **Anything else propagates.** A database outage is not a property of the
   file, so it is not swallowed here; the worker decides how to retry.

## End-to-end run against real PostgreSQL

Four files processed in one loop against the running PostgreSQL service. No
file raised an exception; the loop completed.

| File | Version status | error_code | Chunks |
| --- | --- | --- | --- |
| normal.pdf | basic_ready | (none) | 3 |
| encrypted.pdf | unsupported | `encrypted` | 0 |
| corrupt.pdf | unsupported | `corrupt` | 0 |
| no_text_layer.pdf | unsupported | `no_text_layer` | 0 |

This is the schedule's requirement in miniature: a normal document reaches
`basic_ready` with chunks attached, each abnormal document is recorded with its
own reason, and a failure is isolated to its file.

## Automated verification

Command:

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_handler.py
```

Covered:

- successful extraction marks the version `basic_ready`, stamps
  `parser_revision`, and stores the chunks
- each of the three abnormal documents is recorded, not raised, with its own
  reason code and no chunks
- a version whose file changed underneath it is marked failed with
  `source_changed` and stores nothing
- an unknown version id raises, because that is a programming error rather
  than a property of a document
- **one bad file does not stop the next one** - a corrupt file followed by a
  good file leaves the good file fully extracted
- re-processing a version replaces its chunks instead of duplicating them

Full suite at this commit: **40 passed, 1 skipped**. `ruff check .` clean.

## Fix made along the way

`file_identity` accepted only `Path` while `extract_document` accepted either a
string or a `Path`. That inconsistency surfaced the moment the two were used
together. `file_identity` now accepts both, like its sibling.

## What is still not here

- **No worker wiring.** A's dispatch loop does not call this handler yet. Until
  it does, nothing runs automatically; the handler has only been driven
  directly.
- **No job outcome.** Marking the job completed or failed is A's transaction.
- **No evidence read path.** Returning a stored passage for a given version and
  page (10.17 AM) is the next step.
