# B speaking notes, three slides, three minutes

Final script for slides 4 to 6. Timings are for a normal pace at roughly 150
words a minute. Read it aloud twice before the rehearsal; the numbers are the
part most likely to drift.

---

## Slide 4 - "Page 7" has to be true

**Target: 55 seconds. Spoken length: about 140 words.**

> Everything we show the user is meant to point at a page and a passage, so the
> page number has to be right. We did not check that with our own code, because
> checking your own output with the same code proves nothing.
>
> We used a second PDF library, one the pipeline does not use, and looked for
> twelve sampled passages inside the pages they claimed. All twelve agreed. We
> also went through all sixty-six pages at character level: no dropped glyphs,
> no mojibake. So what you see as "the original text" really is the original
> text, and the page it points at is the page it came from.
>
> The check is a script in the repository, so it can be re-run rather than
> taken on trust.

**Pause here.** Let the number land before moving on.

---

## Slide 5 - A relation without a quote is a claim you cannot check

**Target: 60 seconds. Spoken length: about 155 words.**

> The second thing we built is the smallest version of entity finding the
> schedule asks for: three candidates, one person, one project, one topic, each
> carrying the page and the sentence it came from. If we cannot show you the
> sentence, we do not store the relation.
>
> This is a rule, not a model, and I want to be precise about how well it works.
> On real lecture slides the rules first produced forty-seven candidates, most
> of them words that start a sentence. Skipping line-initial words took that to
> thirty-nine; ranking by how often a term recurs and keeping ten left mostly
> the document's real recurring terms. About three in four are right.
>
> That is good enough for a list a person reviews. It is not good enough to
> call it automatic extraction, and we are not claiming that.

---

## Slide 6 - Decisions are appended, never replaced

**Target: 60 seconds. Spoken length: about 150 words.**

> Every rule output in this system can be regenerated, so it is safe to throw
> away. Human decisions are the exception: once a reviewer confirms or rejects
> a relation, recomputing it is data loss.
>
> So a decision is appended with a revision number, and whoever submits one has
> to say which revision they were looking at. In the demo you will see reviewer
> A confirm at revision one. Reviewer B is holding an older view, so the system
> refuses the write with a conflict instead of silently overwriting A. B
> re-reads, and then rejects at revision two.
>
> A's original decision is still in the history afterwards. That is the whole
> point: the record of who decided what, and when, survives.

---

## If we are running long

Cut in this order:

1. The sentence about the check being a script, on slide 4.
2. The last paragraph of slide 5, keeping only "about three in four".
3. Nothing on slide 6 - the conflict demonstration is the part worth watching.

## Questions we should expect

Ten answers, all short enough to say in twenty seconds. Each one is a fact in
`evidence-final.md` or in a file named beside it.

These are about this slice. Questions about the system rather than the slice -
why the work happens in a worker, why versions are content-hashed, what is
planned for search - are answered in
`submissions/week07/B-answers-on-system-design.md`.

**"How accurate is the entity finding?"** About three in four on the bounded
list, measured on real slides. It is a rule set, and we bounded it to ten
because the schedule asked for candidates rather than a graph.

**"Is the page number verified?"** Yes, against a different PDF library than
the one we use, twelve of twelve. The script that does it is in the repository,
so it can be re-run rather than believed.

**"How do we know the check itself is honest?"** The script refuses to run
without a second PDF library installed, because the fallback would have
compared our own extraction with itself and still printed a pass. Each row
also prints the hash of the exact bytes the passage came from, so a reader can
check it against their own copy of the file.

**"Is this connected to the API?"** Not yet. These are handlers; the routes and
the worker dispatch are A's work, and we say so on the slide rather than
implying it is live.

**"What happens to a file we cannot read?"** It is recorded with a reason -
encrypted, damaged, no text layer, unreadable, unsupported format - and the
scan continues. We proved the isolation by running a corrupt file and then a
good one through the same handler; the good file still completes.

**"Why not store the whole page instead of chunks?"** Because the citation unit
is a passage, and a passage needs a size. Seven hundred characters with a
hundred and twenty of overlap, and a chunk never crosses a page boundary, so
"page seven" is exactly true for everything stored against page seven.

**"What if the file changes while it is being read?"** Extraction returns the
hash of the bytes it actually read. If that differs from the hash the version
was created with, the chunks are thrown away and the version is marked failed
with `source_changed`, because publishing them would attach text from one set
of bytes to a record claiming another.

**"When is a passage refused?"** When the chunk no longer exists, when the file
is gone, when the folder's authorisation was revoked, or when the version has
been superseded by a newer one. Each has its own reason code so the interface
can say which. The honest caveat: nothing sets `current_version_id` yet, so
until A wires that, every read would report itself as stale.

**"What stops two reviewers overwriting each other?"** A decision is appended
with a revision number and the caller must quote the revision it saw. A stale
one is refused with `review_conflict` instead of quietly winning. The demo
shows exactly that: reviewer A at revision one, reviewer B refused, then
allowed at revision two.

**"What does a correction store?"** The decision, the reason, and now the
entity it points at instead. A correction that names no replacement is
refused, because otherwise it is only a rejection with a different word on it.

## Do not say

- "The AI found these entities." It is a rule set.
- "The graph shows relationships." There is no graph view.
- "This is running in the product." It is verified by tests and scripts, and
  not yet wired to the API.
