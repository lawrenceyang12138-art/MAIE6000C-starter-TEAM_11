# B - Chunk write-back against a real file version (10.15 PM)

Owner: B (read files / PDF parsing and evidence quality)
Module: `services/parsing/persist.py`

## The two rules this step implements

1. **Replace, do not append.** A file version is identified by its content
   hash, so the same version always yields the same chunks. Re-processing must
   land on the same rows instead of adding a second copy. The same rule makes a
   parser upgrade safe: the version's chunk set is replaced.
2. **Delete and insert are one transaction.** Replacing means removing the old
   rows first, so a failed insert must roll the delete back too. Otherwise a
   failed re-parse would leave a version with no chunks at all - worse than not
   running it.

3. **A chunk whose content is unchanged keeps its row.** Added on 2026-10-15,
   after finding the consequence of the first two rules. Relationship evidence
   references chunk ids with a cascading foreign key, so deleting and
   recreating an identical row silently strips the evidence from every relation
   that cites it. Re-processing a version with the same parser did exactly
   that: the relation rows survived, and the quotes they exist to justify were
   gone. Unchanged rows are now kept; changed ones are still replaced, because
   text that differs is a different passage and evidence pointing at it should
   not survive either.

## End-to-end run against real PostgreSQL

This was not a test fixture. It ran inside the API container against the
running PostgreSQL service, using a real 22-page PDF mounted read-only.

| Step | Observed |
| --- | --- |
| 1. Parse | 22 pages, sha256 starts c4341d1da7ac |
| 2. Chunk | 24 chunks |
| 3. Create file version | id starts 49687191 |
| 4. First write | 24 chunks written |
| 5. Repeat write of the same version | 24 chunks written again |
| 6. Rows actually in source_chunks | **24** - no duplicates |
| 7. Distinct pages covered | 1 to 22 |

Step 6 is the point: writing the same version twice leaves the same number of
rows, which is the "repeated scan adds 0 duplicate records" acceptance
criterion for this part of the chain.

Sample rows as stored (text abridged):

| ordinal | page_number | chars | opening |
| --- | --- | --- | --- |
| 1 | 1 | 220 | MAIE 6000C: Engineering AI Products: From ... |
| 2 | 2 | 273 | Today's Rule: Observe the Contract Before ... |
| 3 | 3 | 497 | Session 1 Plan and Team Roles ... |
| 4 | 4 | 394 | Start the Starter System Keep the worker ... |

## Automated verification

Command:

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_persist.py
```

Result: **9 passed**, covering the three cases the schedule names plus the
boundaries around them:

- **normal write** - ordinals, page numbers and text land as given
- **repeated write** - the same version written twice still holds one chunk set
- **parser revision** - a different chunk set replaces the previous one
- **unchanged re-write** - identical chunks keep their row ids, so anything
  pointing at them (relation evidence) survives a re-process
- **changed chunk** - a chunk whose text differs gets a new row rather than an
  update, so evidence against the old text cannot silently persist
- **failed write** - a real database rejection mid-insert leaves the previous
  chunks intact, and the session is still usable afterwards
- **malformed set** - duplicate ordinals are rejected before anything is written
- **isolation** - writing one version does not disturb another version's chunks

Full suite at this commit: **32 passed, 1 skipped**. `ruff check .` clean.

## What is deliberately not here

- **No worker wiring.** The worker dispatch loop belongs to A; this module is
  the handler it calls. The intended composition is: `extract_document(path)`,
  then `chunk_document(document)`, then `persist_chunks(db, version_id, chunks)`.
- **No version bookkeeping.** Marking the version `basic_ready`, recording a
  failure reason, and updating the job are all A's transaction, not B's.
- **No chunk reuse check.** A repeat write replaces the rows rather than
  detecting that the content is unchanged and skipping. That is correct but
  not yet efficient; skipping unchanged work is an optimisation for later.
