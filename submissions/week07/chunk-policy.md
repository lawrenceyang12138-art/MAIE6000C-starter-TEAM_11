# Chunking and page-mapping policy

Owner: B (read files / PDF parsing and evidence quality)
Applies to: `services/parsing/chunking.py`

## Why this policy exists

Chunking decides retrieval quality. Get it wrong and the system either returns
walls of text or matches nothing at all. It also decides whether the page
number we show the user is true. Every rule below exists to protect one of
those two things.

## The rules

| Setting | Value | Why |
| --- | --- | --- |
| Maximum chunk size | 700 characters | Large enough to hold a complete idea, small enough to stay readable in a result list. |
| Overlap between neighbours | 120 characters (~17%) | A sentence cut at a boundary is still complete in at least one of the two chunks. |

Both numbers are measured, not asserted: `scripts/check_parsing_quality.py`
prints the longest stored chunk and the smallest observed overlap per file. On
the three real decks the longest chunks are 699, 639 and 692 characters, so the
maximum holds, and the measured overlaps are 118, 119 and 119 - a character or
two under 120 because each stored chunk is stripped at its edges. The
configured overlap is applied to the source text; the measured one is what a
reader can see.
| Minimum chunk size | 80 characters | Prevents a stub at the end of a page from becoming its own chunk; it is folded into the previous one. |
| Break search window | 220 characters | How far back from the hard limit we will look for a nicer place to cut. |
| Page crossing | **Never** | See below. |

## Rule 1: a chunk never crosses a page boundary

The page is our citation unit. When a result says "page 7", that has to be true
or the whole "show me where it came from" promise is worthless.

If a chunk were allowed to start on page 6 and continue onto page 7, the page
number stored with it would be ambiguous, and a user clicking through would
land at the wrong place half the time. Two consequences follow, and both are
accepted deliberately:

- **A long page produces several chunks** that all carry the same page number.
  They are distinguished by their ordinal.
- **A short page produces a short chunk.** A title page with fifteen words is
  a fifteen-word chunk. It will simply match rarely, which is correct: there is
  little in it to match.

The cost of this rule is that a sentence split across a page break is separated.
That is acceptable because the page break is itself a strong reading boundary,
and because overlap cannot help across a boundary we refuse to cross.

## Rule 2: prefer a natural break

When a page is longer than the limit, the cut point is chosen by searching
backwards from the limit for the best available boundary, in this order:

1. a paragraph break (blank line)
2. a sentence end (`。！？!?` and `.` `;` followed by whitespace)
3. any whitespace
4. a hard cut in the middle of a word

A hard cut is the last resort. When it happens the overlap is what keeps the
text recoverable, and the break search window is large enough that it is rare
in practice.

## Rule 3: clean the text before chunking, not after

Raw extraction carries artefacts that would otherwise be indexed as if they
were content:

- carriage returns from the PDF
- a hyphen introduced where a word was split across a line
- runs of spaces
- a single space inserted between two Chinese characters (`数 据 库`), which is
  an extraction artefact and would break Chinese term matching
- runs of three or more blank lines

Cleaning runs per page, before anything is chunked, so no chunk ever contains
an artefact.

## Rule 4: drop running headers and footers

Course slides and reports repeat a title or footer on every page. Indexed, that
line appears on every page and pollutes results.

The rule is deliberately conservative: only the **first** and **last** line of
a page are candidates, and only when the identical line appears on **at least
three pages** and is under 120 characters. A repeated sentence inside the body
of a page is never removed.

## What this policy does not do

- **No semantic splitting.** The cut is chosen by text shape, not by meaning.
  A sentence that belongs together but has no punctuation will be split.
- **No table reconstruction.** Text extracted from a table keeps whatever order
  the PDF produced, which is often scrambled. Fixing that needs layout-aware
  parsing and is not in the W7 scope.
- **No OCR.** Documents without a text layer are rejected upstream with reason
  code `no_text_layer` rather than passed here.
- **Headers are matched exactly.** A page number in the footer that changes
  every page will not be detected as a footer, because the text differs each
  time.

## How the policy is verified

`tests/unit/test_parsing_chunking.py` checks each rule directly:

- every chunk's text really appears on the page it claims
- no chunk contains text from two different pages
- consecutive chunks on a page share overlapping text
- no chunk exceeds the maximum size after trimming
- cleaning removes the artefacts listed in rule 3
- a header repeated on three pages is dropped; a line that appears once is kept

The page-mapping test runs against a synthetic three-page fixture whose pages
contain distinct marker words, so a page-number mistake cannot pass.
