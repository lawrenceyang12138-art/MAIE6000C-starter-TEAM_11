# B - final evidence record

Owner: B (read files / PDF parsing and evidence quality)

Single entry point for B's side of the milestone. Every number below was
measured on a fresh run before this file was written, not carried over from an
earlier note.

## Verified state

Run inside the api container, at the commit that contains this file.

| Check | Command | Result |
| --- | --- | --- |
| Whole suite | `pytest -q` | **103 passed, 1 skipped** |
| Migrations from an empty database | `alembic upgrade head` against a freshly created PostgreSQL database | four migrations apply in order and reach `445f908b73b4` |
| The commands CI runs | `ruff check .`, the migration step, `pytest -q tests/unit tests/integration` | clean, head reached, **103 passed, none skipped** |
| Independent audit by two blank-context reviewers | materials verified by re-running their own commands; the code attacked with adversarial inputs | every claim reproduced except four stale statements (fixed); the code audit found and reproduced four real defects, all now fixed and pinned by tests (`submissions/week07/B-fixes.md`) |
| A file written while it is being read | `pytest -q tests/unit/test_parsing_pdf.py -k written` | refused with `source_changed`; the window was reproduced by an independent reviewer before the fix |
| A failure while storing | `pytest -q tests/unit/test_parsing_handler.py -k extracting` | the version is recorded `failed` with `processing_failed` instead of staying `extracting` |
| Foreign keys in the test database | `pytest -q tests/unit/test_parsing_graph.py -k restores` | SQLite now enforces them, and the test asserts the cascade really removes the evidence rows |
| Downgrading with a generalised job present | `alembic downgrade 20260713_0001` | succeeds; it deletes jobs the old schema cannot represent |
| B's three minutes, driven live | `submissions/week07/demo-runbook-B.md` | four commands, **3.2 s** of command time, each printing its own numbers |
| The starter's own case flow, after the schema changes | stack up, `pytest -q tests/smoke`, then `POST /cases` on the live API | smoke **1 passed**; the case went `queued` to `triaged` with label `billing` and confidence 0.63, triaged by the worker |
| The same flow driven through a browser | Swagger UI at `/docs` in the in-app browser: expand `POST /cases`, Try it out, fill the body, Execute | **201** with the created case and job; the worker then triaged it (`general`, 0.45). Screenshot: `artifacts/swagger-created-case.png` |
| Rebuilding after a migration change (observed once, on 2026-10-15) | `docker compose up -d` then `docker compose up -d --build` | at the time, without the rebuild the api container exited with `Can't locate revision identified by '445f908b73b4'`; with it, every service was healthy. It no longer reproduces, because the image has since been rebuilt - the row records what happened, not a step to repeat |
| Static analysis | `ruff check .` | clean |
| Independent page attribution | `scripts/verify_page_attribution.py` | **12/12 agree** |
| Parsing quality on three real decks | `scripts/check_parsing_quality.py` | 66 pages, 0 corrupt characters, **20/20** fragments found on their page |
| Documents the parser had never seen | `scripts/sweep_corpus.py` | **0 crashes, 0 refusals, 0 control characters stored** on a folder that has since grown from 38 documents and 1,723 pages to 40 and 1,822; unreadable symbols are marked instead of emitted as control codes. The totals track the folder, so the exit code is the evidence (`evidence/real-corpus-sweep.md`) |
| Entity candidate counts and the bounding steps | `scripts/check_relation_candidates.py` | 47/44/36 before the line-initial rule, 39/38/33 after, **10** bounded, on all three decks |
| A document whose every page is one repeated line | `pytest -q tests/unit/test_parsing_chunking.py` | storing it as ready with **zero chunks** was possible; the header rule can no longer empty a page, and the case has a test |
| Slide 4's picture, produced rather than screenshotted | `scripts/render_evidence_card.py` | `artifacts/page-6-passage.jpg`, `artifacts/api-deck-page-13-passage.jpg` - the real page rendered, our passage highlighted, provenance printed underneath |
| 12 normal / 3 abnormal / 1 unsupported | `pytest -q tests/integration/test_extraction_regression.py` | **7 passed** |
| Relation and review end to end | `scripts/demo_relation_review.py` | 3 candidates, review revisions 1 and 2, and a correction that carries the entity it points at |
| Port to the team repository | the branch is **pushed** (`w7-parsing`), a descendant of `main` so the merge is a fast-forward | 101 passed, 1 skipped in the team tree against 103 and 1 here; the gap of two is the tests the team's uncorrected Week 3 filename hides (`submissions/week07/port-to-team-repo.md`) |

The one skipped test is the starter's smoke test, which needs a running stack
and `SMOKE_BASE_URL`. The page check's independent-reader case used to skip for
want of PyMuPDF; now that the library is a dev dependency it runs, which is why
the skip count went from two to one.

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
| AI Use Statement in the milestone submission | `submissions/week07/ai-use-statement.md` | B's part supplied, A/C/D still blank |
| B section, at least 700 words | `submissions/week07/sections/B.md` | met, 1427 words excluding fenced code blocks; the requirement is 700, so the exact count is not load-bearing |
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
