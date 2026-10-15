# B - Parsing quality check (10.17 PM)

Owner: B (read files / PDF parsing and evidence quality)
Scope: check real chunks against their source pages, look for cleaning damage
or broken page boundaries, and record what was found.

## Method

Three real course PDFs (66 pages in total) were parsed and chunked, then
checked mechanically and inspected by eye.

The mechanical part is a script, so these numbers can be re-run rather than
believed:

```
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts" -v "/path/to/pdfs:/fixtures:ro" api \
  python scripts/check_parsing_quality.py /fixtures/*.pdf
```

It exits non-zero if any corrupt character appears or if a fragment is not
found on the page it claims. Two definitions matter for reading the tables:

- **Chars** is the raw per-page text joined with newlines, taken before the
  cleaning rules run. Cleaning removes about one character per page.
- **Short lines** counts lines shorter than fifteen characters, which on these
  slides means a wrapped title fragment rather than prose.

The fragment table below is the first twenty chunks of the first file, in
storage order. Deterministic sampling is deliberate: a sample chosen by hand
cannot be checked by anyone else.

## Fragment check: 20 chunks against their pages

| # | Page | Chars | Attribution | Double spaces | Short lines | Opening |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 220 | correct | 0 | 2 | MAIE 6000C: Engineering AI Products: |
| 2 | 2 | 273 | correct | 0 | 2 | Today's Rule: Observe the Contract B |
| 3 | 3 | 497 | correct | 0 | 6 | Session 1 Plan and Team Roles |
| 4 | 4 | 394 | correct | 0 | 4 | Start the Starter System |
| 5 | 5 | 508 | correct | 0 | 3 | Live Demo Step 1: Health, Swagger |
| 6 | 6 | 699 | correct | 0 | 4 | Live Demo Step 2: Create a Case |
| 7 | 6 | 128 | correct | 0 | 0 | Delay","description":"Customers are |
| 8 | 7 | 536 | correct | 0 | 5 | Live Demo Step 3: Trigger a Validation |
| 9 | 8 | 347 | correct | 0 | 5 | Live Demo Step 4: Retrieve Current State |
| 10 | 9 | 509 | correct | 0 | 6 | Live Demo Step 5: Start the Worker |
| 11 | 10 | 678 | correct | 0 | 8 | Trace the Contract Through the Repository |
| 12 | 10 | 429 | correct | 0 | 0 | est_create_and_read_case_and_job |
| 13 | 11 | 517 | correct | 0 | 0 | What Is the Contract? |
| 14 | 12 | 654 | correct | 0 | 8 | Activity A: Build an API Contract |
| 15 | 13 | 618 | correct | 0 | 4 | Activity B - API Behavior Test Matrix |
| 16 | 14 | 384 | correct | 0 | 6 | Session 1 Checkpoint |
| 17 | 15 | 325 | correct | 0 | 6 | Session 2: From Evidence to Your System |
| 18 | 16 | 426 | correct | 0 | 6 | Scope the Minimum Viable Interface |
| 19 | 17 | 542 | correct | 0 | 1 | Activity C: Draft the Endpoint Contracts |
| 20 | 18 | 656 | correct | 0 | 0 | Activity D: Assign State Ownership |

**Attribution: 20/20.** Each chunk's full text was found inside the cleaned text
of the page it claims. **Double spaces: 0** - whitespace normalisation holds.

## Character-level scan across 66 pages

| File | Pages | Chars | Replacement chars | Control chars | Line-end hyphens |
| --- | --- | --- | --- | --- | --- |
| Week 5 - Lab | 22 | 11,390 | 0 | 0 | 1 |
| Week 4 - Data Persistence and Schema Design | 23 | 12,299 | 0 | 0 | 0 |
| Week 5 - APIs and Network Communication | 21 | 11,359 | 0 | 0 | 0 |

Zero replacement characters means no glyphs were dropped. Zero control
characters means no mojibake. Both matter more than they look: either would
silently corrupt what the user is shown as "the original text".

## The one line-end hyphen, and why it was left alone

Page 19 of Week 5 - Lab contains:

```
Week 7 Contract-
Test Plan: Team
```

The cleaning rule joins a line-end hyphen only when the next character is
lowercase, because that is the shape of a word broken across a line. Here the
next character is uppercase: this is a real hyphenated compound ("Week 7
Contract-Test Plan"), not a broken word. Leaving it alone is correct, and this
case confirms the rule is not over-eager.

## A false alarm worth recording

An earlier read of these slides, made with a different library, showed the
slide titles interleaved with body text, and it looked like a parsing defect.
Checking the artefact the module actually produces showed the opposite: the
title of page 12 comes out as six consecutive lines in the correct order
(`Activity A:` / `Build an` / `API` / `Contract` / `Evidence` / `Map`), followed
by the body. Two other extraction backends were tested on the same page and
both interleaved it, so the reading order of the current backend is a genuine
advantage rather than a problem.

The lesson recorded here: check the artefact the system actually produces, not
a similar-looking output from another tool.

## Finding: the cleaning rules did not fire on this corpus

Across all three documents:

- hyphenated line breaks joined: **0**
- spaces between Chinese characters removed: **0**
- running headers or footers removed: **0 pages** (the `headers` column of
  `scripts/check_parsing_quality.py`)

The rules are not wrong, they are simply not needed by these files, which were
exported cleanly. They are covered by unit tests with synthetic input, so they
behave as specified, but on this corpus they are unexercised.

This has a direct consequence for the demo: **whether they matter depends on
the fixture corpus D is preparing.** If those PDFs are generated from Word or
LaTeX they will be clean too. If they are scans or exports with repeated
headers, the rules will start mattering. This is worth a five-minute check once
the fixtures land, rather than an assumption either way.

**A measurement trap worth recording.** Running the header rule directly on
raw page text reports three changed pages on this corpus, and all three are
blank lines being trimmed rather than content being dropped. The pipeline
cleans a page first and applies the rule second; measured in that order the
answer is zero. The first attempt at checking this claim got it wrong, in the
harmless direction, which is exactly how a claim that matters can go wrong in
the harmful direction.

## Known limitations, unchanged

- A slide title that wraps across several lines stays on several lines. The
  words are in the right order and all present, so search and page citation are
  unaffected, but the passage reads as a list of short lines rather than a
  paragraph. Reflowing it needs layout-aware reconstruction and is out of W7
  scope.
- Text inside tables keeps the order the PDF produced.
- A footer whose text changes on every page is not detected as a header.

## Verdict

No defect was found that affects the W7 acceptance criteria: page attribution,
character integrity, and failure handling all hold on real data. The items
above are recorded as limitations rather than fixed, and the fixture-corpus
check is carried forward.
