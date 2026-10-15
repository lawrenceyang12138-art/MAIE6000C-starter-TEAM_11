# B reviewing D's materials (10.20 peer review)

Reviewer: B. Subject: D's front-end, integration and acceptance materials.

The schedule assigns cross-review pairs so that every claim is read by someone
who did not write it. Each question below must be answerable from the artefact
itself, not from memory.

## 1. Does every "working" claim have an artefact behind it?

- For each screen D shows, is there a screenshot or a recording of it running,
  or only a mock-up? A mock-up presented as running is the failure mode this
  review exists to catch.
- Where the interface is driven by sample data rather than the real service, is
  that stated on the slide and in the report?
- Do the counts D shows on screen (files, chunks, failures) match what the
  database actually holds at that moment?

## 2. Does the demo path match what exists?

- The acceptance path is: choose a folder, asynchronous parsing, keyword
  search, open the source passage. Can D point at each step in the running
  system, in order?
- Is the corpus used in the demo the frozen one, and is it small enough that the
  waiting time is honest rather than edited out?
- If a step is stubbed, is it marked as stubbed on the slide?

## 3. Do the failure paths exist in the interface?

- The schedule requires four visible states: no results, still indexing,
  degraded search, and a missing source. Are all four reachable and
  distinguishable from one another?
- Is a parse failure shown with its **reason**, or as a generic "failed"?
- When a passage is refused because its version is stale, does the interface say
  why, or does it look like an empty result?

## 4. Are the numbers on the slides traceable?

- For every figure D quotes, which file in `evidence/` produced it?
- Are the semantic-search numbers labelled as an internal smoke test on a fixed
  query set rather than as general performance?
- Is anything quoted from A's or C's work without their evidence file?

## 5. Does the assembled document still agree with its parts?

- Do the section word counts meet the requirement (overall 3000, D's own part
  900)?
- Are the terminology, page numbering and version references consistent between
  the report, the slides and the README?
- Does the README's ten-section structure have any empty fields?

## 6. Delivery mechanics

- Is the deck exactly twelve pages, with each person's three pages contiguous?
- Do the master and the backup machine both open the deck, the PDF and the
  video?
- Is the video the same version as the frozen materials, and does it play with
  the network off?
- Does `release-manifest-final.md` point at a single SHA, and does that SHA
  match the repository?

## What B offers in return

B's own materials are open to the same questions, and specifically:

- the entity precision figure is a measurement with a stated scope, not a
  general claim
- every limitation in `sections/B.md` section 5 is something B chose to write
  down rather than something a reviewer had to find
