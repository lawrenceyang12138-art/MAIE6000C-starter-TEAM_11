# B - Entity candidates with evidence (10.19 AM)

Owner: B (read files / PDF parsing and evidence quality)
Module: `services/parsing/relations.py`, `services/parsing/persist.py`

## What this is, stated plainly

A **rule-based candidate finder, not a model.** The schedule for this step asks
for at least three candidates, at least one of each entity type, each carrying
its page and its source quote, and warns against growing it into a knowledge
graph. Rules are the honest way to meet that bar: deterministic, explainable,
and they do not pretend to understand the text.

What a stored relation claims is deliberately modest: *this document mentions
this name, on this page, in this sentence, as found by this rule.* A person
then confirms, corrects or rejects it.

## The rules

Applied to a capitalised run, in order:

1. ends with a project-ish noun (Project, Platform, System, Assistant, ...)
   -> **project**
2. preceded by a title (Mr, Mrs, Ms, Dr, Prof) -> **person**
3. otherwise a capitalised run appearing in at least two different chunks
   -> **topic**

Articles are stripped from the front first, so "The File Management Assistant"
is recognised as the name "File Management Assistant" rather than rejected for
starting with "The". Single capitalised words at the start of a line are
skipped, because in slides and lists those are sentence openers.

## Result on the controlled fixture

`tests/fixtures/relations/entities.pdf` is a two-page synthetic note built to
contain one of each type. The finder returns exactly three candidates:

| Type | Label | Page | Quote (abridged) |
| --- | --- | --- | --- |
| project | File Management Assistant | 1 | ...Notes page 1 The File Management Assistant indexes documents. Dr. Chen... |
| person | Chen | 1 | ...Notes page 1 The File Management Assistant indexes documents. Dr. Chen... |
| topic | Schema Design | 1 | ...Management Assistant indexes documents. Dr. Chen reviewed the first pr... |

This meets the step's requirement exactly: three candidates, one of each type,
each with its page and the passage that justifies it.

## Result on real slides, and why the output is bounded

The same finder on three real course decks produced **47, 44 and 36 candidates**
respectively, and most were noise: `Observe`, `Create`, `Trigger`, `Retrieve`,
`Trace`, `Session`, `Today` - capitalised words that begin a line because they
begin a sentence or a bullet. (Re-measured at this commit by disabling the
line-initial rule and counting every candidate; the earlier draft of this file
quoted 45 for the third deck, which was wrong.)

This is reproducible rather than retold. The finder takes
`skip_line_initial=False` for exactly this measurement, and the script runs
both ways over the same documents:

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "/path/to/pdfs:/fixtures:ro" api \
  python scripts/check_relation_candidates.py /fixtures/*.pdf
```

It prints the count before the rule, after it, and after bounding, and exits
non-zero if any of the three decks stops matching the numbers recorded here.
A candidate is counted as a distinct **(entity type, label) pair**, because
that is what the bounded list contains; counting mentions instead would report
the same name many times.

`candidate_relations` clamps its `limit` to `MAX_CANDIDATES`, so the bound is a
property of the module rather than a default a caller can talk their way past.
It previously returned however many were asked for, which meant a caller
requesting a thousand candidates got a thousand - the opposite of what this
step is for. `find_mentions` is there for callers who genuinely want every
mention.

Two changes followed, and both are measured rather than assumed:

- skipping line-initial single words took them to **39, 38 and 33**
- ranking by mention count and keeping at most ten produced lists like
  `AI`, `API`, `Worker`, `Client`, `Database`, `Internal`, `POST`, `GET`
  for a document about APIs, with residual noise such as `Which` and `Who`

Precision on that bounded list is roughly three in four. That is usable for a
candidate list a person reviews, and **not** usable as an automatic fact
extractor. Saying so is part of the deliverable.

## A bug the tests caught

Person detection initially failed. The rule checked whether the twelve
characters before a name were a title, but that window contained text from
before the title (`uments.\nDr. `), so it never matched. The check now anchors
to the end of the preceding text instead of assuming the window contains
nothing else. Without the test this would have shipped as "we find no people".

## How relations are stored

`persist_relations` writes entities, relationships and their evidence:

- entities and relationships are **found-or-created**, so a relationship keeps
  its row id across re-runs. This matters later: a human review points at a
  relationship, and replacing the row would silently discard the review.
- evidence rows are refreshed per relationship, because they carry offsets into
  chunk text and a parser change moves them.
- **a relationship cannot be stored without its evidence.** The chunks must
  already exist; citing a chunk that is not stored raises rather than writing a
  relation nobody can check.

## Verification

Command:

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_relations.py
```

Result: **11 passed** (the count grows as cases are added; the command above is
the authority), covering all three entity types, that every candidate's
offset really points at its label inside its chunk, that the page matches, that
quoting is real text, that sentence openers are not treated as names, that a
second run does not duplicate relationships, and that evidence cannot be stored
before the chunks.

Full suite: **64 passed, 1 skipped**. `ruff check .` clean. The new migration
downgrades and re-applies cleanly.

## Boundary note

The schedule gives A ownership of the shared schema, so the four tables added
here (`entities`, `relationships`, `relationship_evidence`, `reviews`) are
written as a **proposal for A to review**, complete with a working migration
rather than a description of fields. They were added in a sandbox branch, not
on top of anyone else's work.

## Not done yet

- The read and review API (the afternoon half of this step).
- Nothing calls the finder from the worker yet.
- No evaluation against the official fixture corpus, which has not landed.
