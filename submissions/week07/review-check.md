# Review verification (10.20 AM)

Owner: B (read files / PDF parsing and evidence quality)
Schedule requirement: one of each decision type recorded, at least two
rejections, with conflicts handled rather than overwritten.

## What was exercised

Three candidate relations from one document, each receiving a decision, plus a
second decision on a relation that had already been decided.

| Relation | Decision | Revision | Actor | Reason recorded |
| --- | --- | --- | --- | --- |
| 1 (person `Chen`) | confirmed | 1 | reviewer-a | - |
| 2 (project `File Management Assistant`) | corrected | 1 | reviewer-a | label should be the full name |
| 3 (topic `Schema Design`) | rejected | 1 | reviewer-b | not an entity |
| 1 (person `Chen`) | rejected | 2 | reviewer-b | changed my mind |

All three decision types are present. There are two rejections. The fourth row
is the interesting one: a relation that was confirmed at revision 1 is later
rejected at revision 2, and **the confirmation is still stored**.

## Final effective state

| Relation | Effective decision | Revision |
| --- | --- | --- |
| person `Chen` | rejected | 2 |
| project `File Management Assistant` | corrected | 1 |
| topic `Schema Design` | rejected | 1 |

## Conflict behaviour

Recorded separately in `evidence/relation-review.md`, from a run against real
PostgreSQL: a reviewer holding a stale revision is refused with
`review_conflict` and the earlier decision remains effective. Nothing is
overwritten silently.

## Verification

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_graph.py
```

Result: **17 passed** (the count grows as cases are added; the command above is
the authority), including the three-decision case above, the stale
revision refusal, the append-only history assertion, the refusals for an
invalid decision value and an unknown relation, and the four correction cases:
a correction storing its replacement entity, a correction with no target, a
confirmation that tries to carry a target, and a target that is not an entity.
It also covers evidence that names a chunk from another version and evidence
whose stored chunk text has changed; neither may be displayed as valid evidence.

## What this does not cover

- The reviews here were recorded by calling the handler directly. No HTTP
  endpoint exists yet, so nothing has been exercised through the API or the
  browser.
- A `corrected` decision has to point at an entity that already exists. It
  cannot create one, so correcting towards a brand-new entity is a two-step
  job until someone decides otherwise.
