# B - Chunking and page mapping samples (10.14 PM / 10.15 AM)

Owner: B (read files / PDF parsing and evidence quality)
Policy: `submissions/week07/chunk-policy.md`
Module: `services/parsing/chunking.py`

## What was built

`chunk_document(document)` turns an `ExtractedDocument` into located chunks:

- text is cleaned per page first (hyphenated line breaks, whitespace runs,
  spaces inserted between Chinese characters, blank-line runs)
- running headers and footers are removed when an identical first or last line
  appears on at least three pages
- each page is then split into overlapping chunks of at most 700 characters,
  preferring a paragraph break, then a sentence end, then whitespace
- **a chunk never crosses a page boundary**, so the stored page number is
  always exactly true

## Sample chunks with their pages

Source: one real 22-page course lab PDF, mounted read-only. It produced 24
chunks. The first 20 are listed with the page each one claims.

Text is abridged to 60 characters for this table; the check below used the full
chunk text.

| # | Page | Chars | Attribution check | Opening 60 characters |
| --- | --- | --- | --- | --- |
| 1 | 1 | 220 | pass | MAIE 6000C: Engineering AI Products: From Prototype to Produ |
| 2 | 2 | 273 | pass | Today's Rule: Observe the Contract Before You Extend It... |
| 3 | 3 | 497 | pass | Session 1 Plan and Team Roles Session 1 Plan - Observe the r |
| 4 | 4 | 394 | pass | Start the Starter System Keep the worker stopped at first... |
| 5 | 5 | 508 | pass | Live Demo Step 1: Health, Swagger, and OpenAPI Check Service |
| 6 | 6 | 699 | pass | Live Demo Step 2: Create a Case Through the AP Create a Vali |
| 7 | 6 | 128 | pass | Delay","description":"Customers are experiencing unusually l |
| 8 | 7 | 536 | pass | Live Demo Step 3: Trigger a Validation Error Send Valid JSON |
| 9 | 8 | 347 | pass | Live Demo Step 4: Retrieve Current State and a Missing Recor |
| 10 | 9 | 509 | pass | Live Demo Step 5: Start the Worker and Observe the API Bound |
| 11 | 10 | 678 | pass | Trace the Contract Through the Repository Trace One Endpoint |
| 12 | 10 | 429 | pass | est_create_and_read_case_and_job Useful repository searches |
| 13 | 11 | 517 | pass | What Is the Contract? Moment What the caller should know Aft |
| 14 | 12 | 654 | pass | Activity A: Build an API Contract Evidence Map Team activity |
| 15 | 13 | 618 | pass | Activity B - API Behavior Test Matrix Team activity - 8 minu |
| 16 | 14 | 384 | pass | Session 1 Checkpoint Before Session 2, each team should have |
| 17 | 15 | 325 | pass | Session 2: From Evidence to Your System From Observed API Be |
| 18 | 16 | 426 | pass | Scope the Minimum Viable Interface Start With Two Required E |
| 19 | 17 | 542 | pass | Activity C: Draft the Endpoint Contracts Define: 1. POST / |
| 20 | 18 | 656 | pass | Activity D: Assign State Ownership, Errors, and Boundaries |

**Attribution check: 20/20.** Each chunk's full text was searched inside the
cleaned text of the page it claims. A page-number mistake cannot pass this
check, because the page texts do not share long passages.

## What this sample set demonstrates

- **A long page produces several chunks that share one page number.** Pages 6
  and 10 each produced two chunks (rows 6/7 and 11/12). This is the intended
  consequence of never crossing a page boundary.
- **No chunk exceeded the size limit.** The largest here is 699 characters
  against a 700 character limit; the split lands slightly early because it
  preferred a natural break just before the limit.
- **Short pages stay whole.** Page 1 is a 220 character title page and remains
  a single chunk.

## Automated verification

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_chunking.py
```

Result: **13 passed**. The tests cover page attribution, the no-crossing rule,
the configured overlap, the size bound, ordinal sequencing, each cleaning rule,
and header/footer removal including the negative case (a line that does not
repeat is kept).

Full suite at this commit: **25 passed, 1 skipped**. `ruff check .` clean.

## Known limitations (not yet addressed)

- Text inside tables keeps the order the PDF produced, which is often
  scrambled. Layout-aware reconstruction is out of W7 scope.
- A footer whose text changes on every page (a page number) is not detected,
  because detection matches identical lines.
- Splitting is based on text shape, not meaning.
- Chunks are not written to `source_chunks` yet; that is the next step and
  needs a real file version row to attach to.
