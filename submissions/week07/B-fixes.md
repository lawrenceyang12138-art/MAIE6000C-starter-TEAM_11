# B closeout for the M1 gate (10.18 PM)

Owner: B (read files / PDF parsing and evidence quality)

## What the M1 check found

The independent page-attribution check (see `m1-evidence.md`) sampled twelve
passages across three real documents and **all twelve agreed** with an
independent extractor. No page-mapping or content inconsistency was found, so
there was nothing of that kind to fix.

## One defect was found and fixed

While building the regression corpus, feeding a non-PDF file to the extractor
reported the document as **corrupt**. That is the wrong message: a plain text
file is not a broken PDF, it is a file type we do not handle.

`extract_document` now checks the `%PDF-` header before handing the file to the
PDF reader and reports `unsupported_format` when it is absent. The reader can
now say "we do not handle this kind of file" separately from "your PDF is
broken", which are different things to tell a user.

This also matters for the acceptance criterion "1 unsupported file keeps a
record": previously such a file was recorded with a misleading reason.

## A second defect, found later and fixed the same way

Feeding the handler a path that does not exist - a file deleted between the
scan and the parse - raised `FileNotFoundError` straight out of the handler.

Two things made that worse than it looks. The handler's own docstring promises
that a bad document does not raise, and the version row had already been
committed as `extracting` before extraction started. So the file was recorded
as permanently mid-extraction, with the worker's failed job as the only trace
of why, and a retry would not necessarily clear it.

A missing file now raises `SourceMissing` with the reason `file_missing`, and
the handler records it as **failed** - not `unsupported`. It is a folder that
changed under us rather than a document we cannot read, and it is retryable
once the file is back.

## A third defect, and this one broke an invariant in B's own module

Re-processing a version - which is what a retry or a parser upgrade does -
deleted its chunks and wrote new ones. Relationship evidence references chunk
ids with a cascading foreign key, so the database correctly removed the
evidence rows along with the chunks, and the relations were left **without the
passage that justifies them**. The read path served them with an empty quote,
which looks like a display bug rather than a fact about the data.

Measured on the real database, not inferred: three relations, three quotes
before the re-process, **zero** after it.

Two changes:

- unchanged chunks keep their rows, so a re-process with the same parser no
  longer disturbs the evidence pointing at them
- a relation whose evidence has genuinely gone is now served with
  `evidence_missing = true` instead of a blank quote, and re-running the
  relation step restores it

The module's stated rule is that a relation cannot be stored without its
evidence. Until this was fixed, re-processing a version quietly broke that rule
for every relation in it.

## Then an independent audit ran, and found four more

Two reviewers with no prior context and no knowledge of these documents were
asked to falsify the work. One checked the materials' numbers, one attacked the
code. Between them they reproduced everything the materials claim, and found
four things that were not true or not tested:

| # | What was wrong | How it was found | Fix |
| --- | --- | --- | --- |
| 4 | The file was hashed and then **read again**; a write landing between the two reads was invisible, so text from one set of bytes could be published under the hash of another. Reproduced at a 2 ms write into a ~44 ms window on a 1 MB document | the audit wrote to the file mid-read and watched `basic_ready` come back with the new text | the file is hashed again after the read and the two must agree, or the version is failed with `source_changed`; pinned by a test that writes during the read |
| 5 | A failure while storing left the version saying `extracting` forever, with no error code | the audit made `persist_chunks` raise and read the row back | the outcome is recorded as `failed` with `processing_failed` before the error goes up for the worker to retry |
| 6 | Every test ran on SQLite, which **ignores foreign keys unless switched on**, so the cascade the chunk replacement depends on was never exercised by the suite | the audit compared PostgreSQL with SQLite on the same scenario | the test engine switches foreign keys on, and the graph test now asserts the evidence rows are actually removed rather than left dangling |
| 7 | `alembic downgrade` failed with a not-null violation as soon as one generalised job existed | the audit inserted a job with no case, then downgraded | the downgrade deletes jobs the old schema cannot represent, and says so |

None of the four could have been found by re-reading the documents, which is the
point of asking someone else to attack the work. The audit also confirmed what
it could not break: page boundaries, chunk sizes and overlap, the candidate cap
under absurd limits, every evidence refusal, the write-back transaction, the
review guard under two real concurrent threads, and migrations from an empty
database.

## Regression: 12 normal, 3 abnormal, 1 unsupported

The official fixture corpus is D's deliverable and has not landed yet, so this
run uses a **rehearsal corpus** built for the purpose:

- `tests/fixtures/regression/group-a/` and `group-b/`: twelve generated PDFs,
  two or three pages each, every page carrying a marker like `Marker03P2`
- the three abnormal PDFs already used for parsing tests
- one `.txt` file for the unsupported-format path

When the official fixtures arrive, only the file list changes.

| Outcome | Count | Expected | Result |
| --- | --- | --- | --- |
| Normal documents extracted | 12 | 12 | met |
| Abnormal PDFs reported with a reason | 3 | 3 | met |
| Unsupported file type reported clearly | 1 | 1 | met |

Each normal document's chunks were also checked against the marker on each
page, so page mapping is verified across twelve documents rather than one.

Command:

```
docker compose run --rm --no-deps api pytest -q tests/integration/test_extraction_regression.py
```

Result: **7 passed**.

## Full suite at this point

```
docker compose run --rm --no-deps api pytest -q
```

Result: **54 passed, 1 skipped**. `ruff check .` clean.

The skipped test is the starter's smoke test, which needs a running stack and
`SMOKE_BASE_URL`; it is not an extraction test.

## What B's side now covers

| Schedule item | Evidence |
| --- | --- |
| 10.14 parsing baseline | `evidence/parsing-baseline.md` |
| 10.14-10.15 chunking | `evidence/chunking-samples.md`, `submissions/week07/chunk-policy.md` |
| 10.15 write-back | `evidence/chunk-persistence.md` |
| 10.16 handler and failure isolation | `evidence/extraction-handler.md` |
| 10.17 evidence read path | `evidence/evidence-read-path.md` |
| 10.17 quality check | `evidence/pdf-quality.md` |
| 10.18 independent M1 check | `submissions/week07/m1-evidence.md` |
| 10.18 regression | this file |

## Still open, and not B's to close alone

- **Nothing sets `file.current_version_id`.** Until A's scan or the handler
  sets it, every evidence read will report the passage as stale.
- **The API and worker do not call any of this yet.** Everything so far is
  driven directly from tests and scripts. Wiring is A's boundary.
- **The official fixture corpus has not landed**, so the regression above used
  a rehearsal corpus. Re-run it against D's fixtures when they arrive - that is
  a five-minute check, not a rebuild.
