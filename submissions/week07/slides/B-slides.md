# B slides 4-6 (content spec)

Owner: B. D assembles the deck; these three pages are B's contribution and
together must fit three minutes of speaking.

**The three pages also exist as a real deck: `B-slides.pptx` in this folder.**
It carries the same content plus the speaker notes, so it can be dropped into
the team deck or projected for rehearsal. It was built with the bundled
presentation tool and passed its structural and layout validation (3 slides,
16:9, one font family across all 27 text runs, no findings). The markdown below
remains the source of truth for the wording; if the two ever disagree, the
markdown is what B intended.

---

## Slide 4 - Parsing and page evidence

**Headline:** "Page 7" has to be true.

**On the slide**

- One claim: every search result points at a page and a passage, and both were
  checked independently.
- Three numbers: **12/12** passages agreed with an independent extractor across
  66 pages; **0** dropped glyphs; **0** mojibake.
- One picture, already produced: `artifacts/page-6-passage.jpg` and
  `artifacts/api-deck-page-13-passage.jpg`. Each is the real slide render with
  our stored passage highlighted on it, and a strip underneath giving the
  page, the chunk ordinal, the file and the content hash. Generate with
  `scripts/render_evidence_card.py`; it refuses to draw a card if the passage
  is not found on the page it claims.

**Speaker notes (about 55 seconds)**

> The product promise is that a result shows you where it came from. That is
> only worth anything if the page number is true, so we checked it against a
> different PDF library than the one we use - checking our own output with our
> own code would prove nothing. Twelve sampled passages across three documents,
> all twelve agreed. We also scanned all 66 pages at character level: no
> dropped glyphs and no mojibake, so what the user is shown as "the original
> text" really is the original text.

---

## Slide 5 - Minimum relations, each with its evidence

**Headline:** A relation without a quote is a claim you cannot check.

**On the slide**

- One rule stated in a line: project names end in a project word; people follow
  a title; recurring capitalised runs are topics.
- Three candidates, one of each type, each shown with page and quote.
- One honest number: **about three in four precise** on real slides, which is
  why the output is a candidate list for a person, not an answer.

**Speaker notes (about 60 seconds)**

> For the midterm we deliberately built the smallest version: three candidates,
> one of each type, each carrying the page and the sentence that produced it.
> This is a rule, not a model, and we measured it. On real lecture slides the
> rules first produced forty-seven candidates, most of them sentence openers.
> Skipping line-initial words took that to thirty-nine, and ranking by how often
> a term recurs plus keeping ten left roughly three in four real. That is good
> enough for a list a person reviews, and we are not claiming more than that.

---

## Slide 6 - Human review that cannot be silently overwritten

**Headline:** Decisions are appended, never replaced.

**On the slide**

- A two-step timeline: reviewer A confirms at revision 1; reviewer B, holding a
  stale view, is **refused**; B re-reads and rejects at revision 2.
- One line: revision 1 is still stored after revision 2 exists.
- One sentence on why: human decisions are the only thing reprocessing never
  regenerates.

**Speaker notes (about 60 seconds)**

> Every AI or rule output in this system is reproducible, so we can regenerate
> it. Human decisions are the exception: once someone confirms or rejects a
> relation, throwing that away and recomputing it is data loss. So a decision is
> appended with a revision number, and the caller has to say which revision it
> was looking at. If someone else has reviewed in the meantime, the write is
> refused with a conflict rather than overwriting them. In the demo you can see
> reviewer A confirm, reviewer B get refused, then re-read and reject, with A's
> original decision still in the history.

---

## What not to claim

- Do not say "the AI found entities". It is a rule set, and the precision is
  measured and modest.
- Do not say "the graph shows relationships". There is no graph view; there is
  a bounded list of candidates with evidence.
- Do not present any of this as wired into the running API. The endpoints are
  A's work and are not done.
