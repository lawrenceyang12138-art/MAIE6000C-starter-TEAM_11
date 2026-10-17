# AI Use Statement - Week 7 Midterm Milestone

Team 11. `README.md` asks for the AI Use Statement in major submissions, so
this file is the milestone's copy of it.

Each member records their own use, because "the team used AI" is not a
statement anyone can check. **Member B's part is complete. The other three are
still blank** and are marked as such rather than filled in on someone else's
behalf.

## Tools used

- **Member B (Jintong Zhang):** ChatGPT (Codex) desktop app, used during
  development of the parsing and evidence slice.
- Member A: _not yet supplied_
- Member C: _not yet supplied_
- Member D: _not yet supplied_

## Purpose of use

For member B's slice:

- brainstorming
- code scaffolding
- debugging suggestions
- test generation ideas
- documentation improvement
- **other:** generating the three evidence scripts, and re-measuring the
  numbers that earlier drafts of the documents had quoted

## Materially affected files or areas

Everything under member B's ownership was drafted with the assistant in the
loop. In the form the repository keeps:

- `services/parsing/` - eight modules: extraction, chunking, persistence,
  handler, evidence read, entity candidates, relation graph, review
- `services/common/models.py` and three migrations - the file/version/chunk
  tables, the job generalisation, and the relation tables
- `tests/` - unit and integration tests, plus the PDF fixtures
- `evidence/` - eight files recording what was measured
- `submissions/week07/` - the section, the slides, the speaking notes, the
  review check, the handover note and the consistency check
- `scripts/` - `verify_page_attribution.py`, `check_parsing_quality.py`,
  `check_relation_candidates.py`, `render_evidence_card.py`,
  `demo_relation_review.py`
- `submissions/week07/artifacts/` - the two evidence cards on slide 4, rendered
  from the real pages rather than screenshotted from an interface

## Verification performed

**Correctness checks.** The full suite is run in the container from a rebuilt
image: 112 passed, 1 skipped, `ruff check .` clean. The migration set was
applied, reverted and re-applied against PostgreSQL rather than reasoned about.
Three claims that
the documents make are produced by scripts that fail loudly rather than
reporting a pass: page attribution is judged by a different PDF library
(12/12), the twenty sampled fragments are found on the page they claim (20/20
across 66 pages, 0 corrupt characters), and the entity candidate counts are
re-measured with the line-initial rule on and off (47/44/36, then 39/38/33,
then 10).

**Third audit pass.** Re-reading the relation path found seven more defects:
evidence could cite another version, a failed batch could be half-saved later,
malformed offsets were accepted, repeated mentions overwrote earlier evidence,
an old producer revision survived a re-run, the final status commit could still
leave `extracting`, and unsupported outcomes omitted the parser revision. Each
was reproduced before being fixed and now has its own regression test.

**Modifications made.** Two errors that the assistant produced were found and
corrected, and both are recorded rather than quietly fixed:

1. An earlier draft quoted "45 candidates" for the third deck and "33" for the
   first deck after filtering. Both were wrong - 45 was never a number the
   finder produced, and 33 belonged to the third deck. Re-measured, all four
   affected files corrected, difference kept in `evidence-diff.md`.
2. The page-attribution script fell back to the pipeline's own extractor when
   the independent library was missing, and still printed a pass. It now exits
   with an explanation instead.

**Rejected suggestions.** A model-based entity finder (the schedule asks for
bounded candidates and honesty about precision, not a knowledge graph); a
correction that manufactures a new entity from a review (invented data would
end up in the same table as extracted data); and making the correction payload
optional (a correction that names no replacement is only a rejection under a
different word).

**Limitations noticed, and written down rather than hidden.** Entity finding is
a rule set and about three in four of the bounded list is right; the cleaning
rules never fired on the real corpus; nothing sets `files.current_version_id`
yet, so an evidence read would report every passage as stale; and the handlers
are not reachable over HTTP because the routes belong to member A.

**What was done by whom.** This part should be read plainly rather than
flatteringly: the assistant wrote the code, the tests, the scripts and these
documents, and ran every command quoted above. Jintong Zhang set the task for
each work block, decided what to keep and what to cut, supplied the account and
repository the work lives in, and is the person who has to answer for it. That
is the arrangement worth disclosing, and it is why the limitations above are
written into the documents instead of being left out.

## Responsibility statement

I confirm that I understand and can explain all submitted work associated with
this statement.

So that this is checkable rather than a formality, member B's speaking notes
carry the ten questions this slice invites, with an answer each. They cover the
things a reviewer would reasonably probe: how the page number was verified,
what happens to a file that cannot be read, what happens if a file changes
mid-read, when a passage is refused, and what a correction stores. Where an
answer there is not yet something I can give without reading it, that is a gap
to close before the rehearsal rather than something to hide.
