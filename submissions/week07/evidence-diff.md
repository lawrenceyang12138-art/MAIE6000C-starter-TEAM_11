# Evidence consistency check (10.22)

Owner: B (read files / PDF parsing and evidence quality)
Schedule requirement: re-check the claims in B's materials against the
artefacts, fix the differences, leave none.

This is a check of the documents, not of the code. Each factual claim in
`sections/B.md`, `B-notes.md`, `B-slides.md` and `evidence-final.md` was
compared against a fresh measurement at this commit. Anything that could not be
reproduced was changed rather than explained away.

## The ten checks

| # | Claim | Verify by | Result |
| --- | --- | --- | --- |
| 1 | Three decks total 66 pages | page count per file | 22 + 23 + 21 = **66**, agrees |
| 2 | 72 passed, 1 skipped | `pytest -q` | **72 passed, 1 skipped**, agrees |
| 3 | 12/12 page attribution | `verify_page_attribution.py` | **12/12**, agrees |
| 4 | `sections/B.md` is 1147 words | word count excluding code blocks | **1147**, agrees |
| 5 | `B-notes.md` fits three minutes | spoken word count / 150 wpm | **388 words = 2.59 min**, agrees |
| 6 | The fixture yields 3 candidates | `candidate_relations` on it | **3**, agrees |
| 7 | The 12/3/1 regression passes | that test module | **7 passed**, agrees |
| 8 | Candidate counts on real decks | re-measured with the line-initial rule disabled | **disagreed - fixed**, see below |
| 9 | Review revisions 1 and 2 are retained | `demo_relation_review.py` | **agrees** |
| 10 | 16 W7 commits, 8 parsing modules, 10 week07 files | `git rev-list`, directory listing | **all agree** |

Two of those numbers have since moved. Both moves are recorded here rather
than quietly edited into the table above, because a table of reproduced numbers
is worthless if it is silently kept up to date.

| # | At the check | Now | Why it moved |
| --- | --- | --- | --- |
| 2 | 72 passed | **103 passed, 1 skipped** | The missing `corrected` payload was closed, the evidence scripts gained checks that stop them reporting a pass they did not earn, a refusal that named the wrong cause was split in two, a deleted file stopped escaping the handler, re-processing stopped stripping the evidence off relations, the independent page check started running in the image instead of skipping, two reviewers colliding on the same revision now get the conflict the module promises, the candidate list can no longer be asked past its cap, and an independent audit's four findings were fixed and pinned |
| 3 | 12/12 page attribution | **12/12, now with the content hash of each file** | The table showed only the version row id, which is created fresh on every run, so no reader could check it; the script also quietly fell back to a self-check when PyMuPDF was absent |
| 4 | 1147 words | **1427 words** | `sections/B.md` gained the limitations and design paragraphs written after this check, and a paragraph on what the corpus sweep found |
| 10 | 16 commits, 10 week 7 files | **20 commits, 12 week 7 files**, at the time of writing | The review payload, the port note, and the corrections to the materials they touched |

## The one difference that was found

**Claim 8 was wrong in three files.**

The documents said the finder produced "47, 44 and 45 candidates" across the
three decks, and that skipping line-initial words "took 47 down to about 33".

Both numbers were wrong. The 33 belonged to the **third** deck, not the first,
and 45 was not a number this finder ever produced - the third deck gives 36.
Re-measured at this commit by disabling the line-initial rule and counting every
candidate:

| Deck | Before the line-initial rule | After it | After ranking and bounding |
| --- | --- | --- | --- |
| Week 5 Lab | 47 | 39 | 10 |
| Week 4 Data Persistence | 44 | 38 | 10 |
| Week 5 APIs | 36 | 33 | 10 |

The corrected figures are now in `evidence/relation-candidates.md`,
`submissions/week07/sections/B.md`, `B-notes.md` and `B-slides.md`, and each
place records that an earlier draft had them wrong.

**Why this matters more than a typo.** The accuracy of the entity finder is the
one number in B's materials that a reviewer might challenge. Quoting numbers
that cannot be reproduced would undermine the honest framing the rest of the
section is built on. The numbers were wrong because they were carried across
three different runs by hand; re-measuring them is exactly what this step is
for.

## A wording inconsistency, not a factual one

The word counts quoted in conversation used two different measures for a while:
`wc -w` includes code blocks, the count used for `sections/B.md` excludes them.
No document states a word count for the guide, so nothing needed changing, but
the measure used for B's section is stated in the row above so the figure can be
reproduced.

## Remaining differences

**None in the figures.** Every number B's materials quote can now be reproduced
by running the commands in the table.

The one thing this check cannot cover is the fixture corpus: checks 1, 3 and 8
used real course PDFs, and check 7 used the rehearsal corpus, because D's
official fixtures have not landed. When they do, those three checks should be
re-run against them - the commands are unchanged, only the file list is.
