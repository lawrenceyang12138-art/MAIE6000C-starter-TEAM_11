# Week 7 README: B's blocks, paste-ready

Owner: B. Reader: D, who assembles the milestone README.

The schedule says A, B and C each supply their own module's contribution and D
does not write it for them. These are B's blocks for the ten-section README in
`templates/submissions/week07-README-template.md`. Every statement here is
backed by a file or a command in this repository; nothing is written for A, C
or D, and the places where the answer is theirs say so.

## Section 1 - What currently works (B's part)

Reading a document works end to end, as a handler rather than as a route: a PDF
on disk is extracted page by page, split into located chunks, written against a
file version, and every stored passage can be read back with the page it came
from and the hash of the bytes it was read from. Entity candidates are found
for a version, each carrying its page and the sentence that justifies it, and a
reviewer can confirm, correct or reject one with a revision guard that refuses
to overwrite someone else's decision.

What does not work yet: nothing reaches any of this over HTTP, and nothing
calls it from the worker. Those two are A's.

## Section 5 - Current evidence of integration (B's part)

| Path | State |
| --- | --- |
| DB write path | **works** - `source_chunks`, `entities`, `relationships`, `relationship_evidence`, `reviews` are written against a real file version, verified against PostgreSQL |
| API path | not wired - the routes belong to A; the handlers exist and are documented in `handover-to-A.md` |
| worker path | not wired - the dispatch loop belongs to A; the exact change is proposed in `handover-to-A.md` |
| AI path | not used by this slice - entity finding is a rule set, deliberately, and the AI service is separate |
| operational signal | the version carries `status`, `error_code` and `parser_revision`, so a scan can report what happened to each file without parsing logs |

## Section 6 - Testing and verification (B's part)

- Full suite: **103 passed, 1 skipped**; `ruff check .` clean. The one skip needs
  a running stack.
- Migrations apply from an empty database, not only over an existing one.
- Page attribution was judged by a **different PDF library** than the pipeline
  uses: **12/12** sampled passages agreed across 66 pages.
- Parsing quality on the same 66 pages: **0** replacement characters, **0**
  control characters, **20/20** sampled fragments found on the page they claim.
- The entity candidate counts quoted in the section and on the slides are
  re-measured by a script that fails if they stop matching.
- The parser was run over **38 documents it had never seen** (1,723 pages of
  other courses' notes, slides and syllabi): **no crashes, no refusals**. Two
  of them contained symbols whose font encoding has no Unicode mapping; those
  are now marked where they occur instead of being emitted as invisible
  control characters.
- The starter's own case flow still works after the schema changes: smoke test
  passes, and a posted case reaches `triaged` with a label and a confidence.
- The work replays onto the team repository's `main` with **zero conflicts**
  (`port-to-team-repo.md`).

## Section 7 - Risks and revised scope (B's part)

- **Biggest current risk:** nothing sets `files.current_version_id`, so an
  evidence read refuses every passage with `no_current_version`. The demo would
  look broken without an error being raised anywhere. It needs one sentence of
  agreement from A and is the first thing to settle.
- **Biggest cut already made:** relations are a bounded list of ten candidates
  with evidence, not a graph, and the finder is a rule set whose precision is
  measured and stated rather than implied.
- **Biggest cut still available:** drop relations and review from the demo
  entirely and show parsing, page evidence and the refusal behaviour. That
  removes the two parts that depend on A's routes and keeps everything that is
  verified.

## Section 9 - Artifact index (B's part)

| Item | Where |
| --- | --- |
| Module report | `submissions/week07/sections/B.md` |
| Slides 4-6 content | `submissions/week07/slides/B-slides.md` |
| Three-minute script | `submissions/week07/B-notes.md` |
| Live demo runbook, four commands | `submissions/week07/demo-runbook-B.md` |
| Evidence cards for slide 4 | `submissions/week07/artifacts/` |
| Evidence records, eight files | `evidence/` |
| Handover to A | `submissions/week07/handover-to-A.md` |
| How this lands in the team repository | `submissions/week07/port-to-team-repo.md` |
| Every technical decision, its alternatives and the trade-offs | `docs/technical-decisions-and-alternatives.md` |
| How to verify this work without reading code | `docs/how-to-review-and-verify.md` |

## Section 10 - AI Use Statement (B's part)

B's slice was drafted with an AI coding assistant, which is disclosed in full in
`submissions/week07/ai-use-statement.md`: what it was used for, which files it
touched, what was checked and how, which suggestions were rejected, and the
errors that were found and corrected. That file also records the division of
work plainly rather than flatteringly, and the three other members' sections
are still blank for them to fill in themselves.
