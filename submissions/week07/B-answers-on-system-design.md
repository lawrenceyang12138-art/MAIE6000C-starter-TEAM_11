# Answers on system design (B)

Owner: B. These are the questions that go beyond B's three slides - the ones a
teammate, a reviewer or an examiner may ask about the system rather than about
the parsing slice. Every answer is short enough to say out loud, and points at
where the claim can be checked. The full reasoning, with alternatives and
trade-offs, is in `docs/technical-decisions-and-alternatives.md` (Chinese).

---

**"Why not just process the file inside the request?"**

Because the request would block for seconds - minutes for a real model - and a
failure inside a request is not recoverable. Our submit path only validates,
writes a row and enqueues a job; a worker claims it and the client polls the
status. You can see it end to end: the smoke test posts a case and watches it go
from `queued` to `triaged`.

**"Why identify a file version by a content hash instead of a version number?"**

The question we have to answer later is "which exact bytes did this text come
from", not "which came first". A hash answers that directly, makes re-processing
safe, and lets us detect a file that changed while we were reading it. The cost
is that the file must be read to hash it - and that identical bytes can still
produce different text if the parser changes, which is why the parser revision
is stored on the version as well.

**"Why two PDF libraries?"**

Because checking our own output with our own code proves nothing. `pypdf`
extracts; PyMuPDF independently re-extracts, and we search for twelve sampled
passages inside the pages we claim. All twelve agree. The check refuses to run
without the second library rather than quietly grading itself - that fallback
existed once and it printed a pass.

**"Why can a chunk never cross a page?"**

Because the page is the citation unit. If a chunk spanned two pages, "page 7"
would stop being exactly true - and the whole promise is that a result points at
a page the reader can open. The cost is accepted deliberately: a long page
produces several chunks sharing one page number.

**"Why rules instead of a model for the entity candidates?"**

The schedule asks for a small, checkable candidate list, not a knowledge graph.
Rules are deterministic and explainable, and we measured how rough they are:
about three in four of the bounded list are right, which we state rather than
round up. A model would look better and be much harder to defend, because the
same input can give different answers.

**"What about search?"**

That is C's slice and it is not built yet. The plan in the schedule is keywords
first, then a local embedding model with vectors in PostgreSQL, then hybrid
ranking. The requirement I would point at is that **keywords must still work
with the model switched off, and the response must say it degraded** - semantic
search is an enhancement, not a dependency. At the moment there is genuinely no
search module in the repository; that is checkable.

**"There is an AI service - is it a real model?"**

No. The starter's AI service is a keyword scorer with a synthetic confidence
value (0.55 plus 0.08 per keyword hit, capped at 0.95). It is there so the
architecture can be demonstrated offline: a replaceable, timeout-able,
degradable boundary. We never present that number as a probability of being
correct.

**"How do you know any of this works?"**

Every number in our materials is produced by a command, and most of those
commands are scripts that **fail loudly if the number stops matching** rather
than printing a pass. On top of that, an independent reviewer with no prior
context re-ran them and attacked the code; they found four defects, which are
fixed and pinned by tests. `submissions/week07/evidence-final.md` indexes all of
it, and `docs/how-to-review-and-verify.md` explains how to check it without
reading code.

**"What is the biggest thing that is not done?"**

The slice is not reachable over HTTP. There are no routes for evidence,
relations or reviews, the worker's dispatch loop does not claim parsing jobs,
and nothing sets `files.current_version_id`, so an evidence read would refuse
every passage. All three are member A's, and all three are written down as open
items rather than left to be discovered on stage.
