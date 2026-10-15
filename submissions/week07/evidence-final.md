# B - final evidence record

Owner: B (read files / PDF parsing and evidence quality)

Single entry point for B's side of the milestone. Every number below was
measured on a fresh run before this file was written, not carried over from an
earlier note.

## Verified state

Run inside the api container, at the commit that contains this file.

| Check | Command | Result |
| --- | --- | --- |
| Whole suite | `pytest -q` | **78 passed, 2 skipped** |
| Static analysis | `ruff check .` | clean |
| Independent page attribution | `scripts/verify_page_attribution.py` | **12/12 agree** |
| 12 normal / 3 abnormal / 1 unsupported | `pytest -q tests/integration/test_extraction_regression.py` | **7 passed** |
| Relation and review end to end | `scripts/demo_relation_review.py` | 3 candidates, review revisions 1 and 2, and a correction that carries the entity it points at |
| Port to the team repository | rebase onto the team's `main`, then `pytest -q` in that tree | **every commit replays, zero conflicts**; 74 passed, 1 skipped there, the two-test gap traced to the team's uncorrected Week 3 filename (`submissions/week07/port-to-team-repo.md`) |

The skipped tests are the starter's smoke test, which needs a running stack and
`SMOKE_BASE_URL`, and the page check's independent-reader case, which skips
where PyMuPDF is not installed. Neither is an extraction test.

## Requirement to evidence

| Schedule requirement | Evidence | Status |
| --- | --- | --- |
| Per-page extraction keeping page number and file identity | `evidence/parsing-baseline.md` | met |
| Chunking with overlap and page mapping | `evidence/chunking-samples.md`, `submissions/week07/chunk-policy.md` | met |
| Chunks written against a file version | `evidence/chunk-persistence.md` | met |
| Encrypted, damaged and image-only files reported with distinct reasons | `evidence/extraction-handler.md` | met |
| A file changed during extraction is not published | `evidence/extraction-handler.md`, `test_parsing_handler.py` | met |
| Evidence read refuses stale or missing sources | `evidence/evidence-read-path.md` | met |
| Source / version / page agreement, 10 of 10 | `submissions/week07/m1-evidence.md` | met, 12 of 12 |
| 12 normal, 3 abnormal, 1 unsupported | `submissions/week07/B-fixes.md` | met |
| At least three relation candidates, one of each entity type, each with page and quote | `evidence/relation-candidates.md` | met, exactly three on the controlled fixture |
| One of each review decision, at least two rejections | `submissions/week07/review-check.md` | met |
| A correction carries the entity it points at | `evidence/relation-review.md`, `submissions/week07/handover-to-A.md` | met |
| B section, at least 700 words | `submissions/week07/sections/B.md` | met, 1300 words excluding code blocks |
| Three slide pages | `submissions/week07/slides/B-slides.md` | met |
| Cross review of D | `submissions/week07/B-review-of-D.md` | prepared, not yet run |

## The numbers that matter in the demo

- **12 of 12** sampled passages agreed with a different PDF library than the
  pipeline uses. The M1 criterion asks for 10 of 10.
- **0** dropped glyphs and **0** mojibake across 66 pages.
- **3** candidates on the controlled fixture, one person, one project, one
  topic, each with its page and its quote.
- **About three in four** precise on real slides once the list is bounded to
  ten. Stated as a measured limitation, not as a capability.
  The bounding steps were re-measured at this commit: 47, 44 and 36 candidates
  with the line-initial rule disabled, 39, 38 and 33 with it, 10 after ranking.
- Review revisions **1 and 2** both retained after the second decision; a stale
  reviewer refused rather than allowed to overwrite.
- A correction that names no replacement is refused, so a `corrected` row can
  never mean "wrong, but nobody wrote down what was right".

## Open items, and whose they are

| Item | Owner | Why it matters |
| --- | --- | --- |
| Nothing sets `file.current_version_id` | A | Until it is set, every evidence read reports the passage as stale |
| No HTTP endpoints for evidence, relations or review | A | Everything below is a handler; nothing is reachable from the browser |
| Nothing calls the handlers from the worker | A | No document is processed automatically yet |
| The four relation tables are a proposal, not an agreed schema | A | The migration works; A owns the final decision |
| Official fixture corpus has not landed | D | The 12/3/1 regression used a rehearsal corpus and should be re-run |
| Cleaning rules never fired on the real corpus | D/B | Worth a five-minute check against the official fixtures |
| A correction cannot create an entity, only point at one | A/B | Creating an entity from a review is a separate decision, so a new label takes two steps |

## Two questions B should be able to answer in the Q and A

**"How do you know the page number is right?"**

Because it was checked against a different tool than the one it was produced
with. Twelve sampled passages were looked for in pages extracted by a second
PDF library, using three separate windows of text per passage so a single lucky
match could not pass. All twelve agreed. Checking our own output with our own
code would have proved nothing.

**"Why is the entity list so short, and how accurate is it?"**

The schedule for this step asked for at least three candidates and explicitly
warned against building a knowledge graph, so the list is bounded to ten in
code. Accuracy is about three in four on real lecture slides: the rules first
produced 47, 44 and 36 candidates across three decks, mostly sentence openers;
skipping line-initial words took those to 39, 38 and 33; ranking by mention
count and keeping ten put the document's real recurring terms at the top. It is
a candidate list for a person to review, and we are not claiming more than
that.

## Where to start reading

For the shortest path into this work: `submissions/week07/sections/B.md` for the
narrative, then `evidence/relation-review.md` and
`submissions/week07/m1-evidence.md` for the two strongest pieces of evidence.
