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

## If we are challenged

**"How accurate is the entity finding?"** About three in four on the bounded
list, measured on real slides. It is a rule set, and we bounded it to ten
because the schedule asked for candidates rather than a graph.

**"Is the page number verified?"** Yes, against a different PDF library than
the one we use, twelve of twelve.

**"Is this connected to the API?"** Not yet. These are handlers; the routes are
A's work and we say so on the slide.

## Do not say

- "The AI found these entities." It is a rule set.
- "The graph shows relationships." There is no graph view.
- "This is running in the product." It is verified by tests and scripts, and
  not yet wired to the API.
