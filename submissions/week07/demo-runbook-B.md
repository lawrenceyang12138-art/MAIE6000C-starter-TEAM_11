# B's three minutes, live: runbook

Owner: B. Everything below was run in this order on 2026-10-15, and the outputs
quoted are the ones those runs produced.

**Why this exists.** B's three slides promise page evidence, bounded relation
candidates and a review conflict. The interface that would show any of that is
A's work and is not wired yet, so this runbook drives the same evidence from
scripts instead. **Total command time is under four seconds**; everything else
is the talking. If the demo machine misbehaves, the recording of these same
commands is the backup.

## Timing budget, measured

| Part | Time |
| --- | --- |
| Spoken script (`B-notes.md`, about 388 words at ~150 wpm) | **about 2 min 35 s** |
| Four commands, run back to back, container start included | **3 s** (1 + 1 + 1 + 0) |
| Showing the card, switching windows, pointing at the output | budget 15 s |
| **Total** | about **2 min 53 s**, leaving roughly 20 seconds of slack |

The slack is the point: if a command is slower on the day, or someone asks a
question mid-flow, there is room. If it is running long, cut in the order
`B-notes.md` gives rather than skipping a command - an unrun command removes
the evidence the sentence is about.

## Before the session (five minutes, not on stage)

```
docker compose up -d --build
docker compose ps
```

`--build`, not a plain restart: the image carries its own copy of the
migrations, and a container built before the newest one exits with
`Can't locate revision identified by '445f908b73b4'`.

```
DECKS="/Users/zhangjintong/HKUST/HKUST-6000C"
```

Check the three decks are readable, open the two evidence cards so slide 4 has
its picture without waiting
(`artifacts/page-6-passage.jpg`, `artifacts/api-deck-page-13-passage.jpg`), and
keep the recorded backup one click away.

## On stage

### Show the card (no command)

`artifacts/page-6-passage.jpg` - the real slide, our stored passage highlighted,
the page, chunk ordinal, file name and content hash printed underneath.

> "Everything we show points at a page and a passage. This is a passage we
> stored, found again on the page it claims, with the hash of the bytes it came
> from. We did not check that with our own code."

### Step 1 - the corpus is clean (0.8 s)

Pass the three decks explicitly. A wildcard would also pick up every other PDF
in that folder and the numbers below would stop being the numbers measured.

```
DECKS="/Users/zhangjintong/HKUST/HKUST-6000C"
DECK1="$DECKS/Week 5 — Lab.pdf"
DECK2="$DECKS/Week 4 — Data Persistence and Schema Design.pdf"
DECK3="$DECKS/Week 5 — APIs and Network Communication.pdf"

docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "$DECKS:/fixtures:ro" api \
  python scripts/check_parsing_quality.py \
    "/fixtures/Week 5 — Lab.pdf" \
    "/fixtures/Week 4 — Data Persistence and Schema Design.pdf" \
    "/fixtures/Week 5 — APIs and Network Communication.pdf"
```

Produces: 3 files, 66 pages, 35,048 characters, **0 corrupt characters**,
**20/20** sampled fragments found on the page they claim, **0** pages changed
by the running-header rule.

> "Sixty-six real pages, no dropped glyphs and no mojibake, and every sampled
> fragment is on the page it says. The script exits non-zero if that stops
> being true."

### Step 2 - judged by a different library (1.0 s)

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "$DECKS:/fixtures:ro" api \
  python scripts/verify_page_attribution.py \
    "/fixtures/Week 5 — Lab.pdf" \
    "/fixtures/Week 4 — Data Persistence and Schema Design.pdf" \
    "/fixtures/Week 5 — APIs and Network Communication.pdf" --per-file 4
```

Produces: **12/12 agree**, each row naming the content hash of the file it came
from.

> "A second PDF library - not the one the pipeline uses - looked for twelve
> sampled passages inside the pages we claim. All twelve agreed. The script
> refuses to run without that second library, because a check that grades
> itself proves nothing."

### Step 3 - candidates, and how far they were cut (0.8 s)

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "$DECKS:/fixtures:ro" api \
  python scripts/check_relation_candidates.py \
    "/fixtures/Week 5 — Lab.pdf" \
    "/fixtures/Week 4 — Data Persistence and Schema Design.pdf" \
    "/fixtures/Week 5 — APIs and Network Communication.pdf"
```

Produces: **47 / 44 / 36** candidates with the line-initial rule off, **39 / 38
/ 33** with it on, **10** after ranking - and it exits non-zero if those
recorded numbers stop matching.

> "This is a rule set, not a model, and we measured how rough it is. Most of
> those candidates were sentence openers. What survives is a list a person
> reviews, and about three in four are right."

### Step 4 - a decision that cannot be overwritten (0.6 s)

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "$PWD/tests:/app/tests" api \
  python scripts/demo_relation_review.py tests/fixtures/relations/entities.pdf
```

Produces, in order: reviewer A confirms at revision **1**; reviewer B with a
stale view is **refused** with `review_conflict`; B re-reads and rejects at
revision **2**; a correction points at the entity it should be instead; a
correction that names no replacement is **refused**.

> "Human decisions are the one thing recomputing never gives back. So a
> decision is appended with a revision number, and you have to say which
> revision you were looking at. Watch A's original decision survive underneath
> B's."

## If something goes wrong

- **"PyMuPDF is not installed, so the only reader available is the one under
  test."** That is the script refusing on purpose. Say so, show the card, and
  continue - it is a better moment than a green tick.
- **Docker cold or slow.** Steps 1-3 read PDFs and need no stack at all; step 4
  needs the database. If Docker will not cooperate, switch to the recording.
- **A command prints a mismatch.** Do not explain it away on stage: say the
  recorded number no longer reproduces and that it needs checking.

## What not to claim

- not "the AI found these entities" - it is a rule set with measured precision
- not "the graph shows relationships" - there is a bounded list, not a graph
- not "this is running in the product" - these are handlers and scripts; the
  routes and the worker wiring are A's and are not done
