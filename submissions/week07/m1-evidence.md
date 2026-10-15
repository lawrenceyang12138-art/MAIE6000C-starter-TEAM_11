# M1 evidence check - source, version and page agreement (10.18)

Owner: B (read files / PDF parsing and evidence quality)
Milestone: M1, the narrowest-chain gate
B's M1 criterion: sampled passages agree with source, version and page (10/10)

## How this was checked

A check of B's own work must not use B's own extraction to do the checking.
Re-running the same code and comparing it with itself proves nothing, so each
stored passage was searched for in a page produced by a **different** tool:
PyMuPDF, an independent PDF library, while the pipeline itself uses pypdf.

For every sampled passage:

- three 30-character windows were taken from the stored text, at 25%, 50% and
  75% of its length, so a single lucky match cannot pass the check
- all three windows had to be present in the independently extracted text of
  the page the passage claims
- both sides were whitespace-normalised only, so the comparison is about
  content and location, not formatting

The check is reproducible:

```
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/app/scripts" -v "/path/to/pdfs:/fixtures:ro" api \
  python scripts/verify_page_attribution.py /fixtures/*.pdf --per-file 4
```

PyMuPDF is in the `dev` extras now, so the command needs no install step of its
own: it used to spend twenty-seven seconds on `pip install` while someone was
supposed to be talking, which is twenty-seven seconds too many on stage.

The script **refuses to run without a second reader** rather than falling back
to the pipeline's own extractor. That fallback existed and was silent: on a
machine without PyMuPDF the check would have compared our extraction with
itself and still printed a pass. `--allow-self-check` runs it anyway and labels
the output `NOT independent`.

## Result: 12 of 12 agree

Three real documents, 66 pages in total, four sampled passages from each.

| # | File | Page | Version | Content | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | Week 5 - Lab | 1 | 0f27cd30 | c4341d1d | agrees |
| 2 | Week 5 - Lab | 6 | 0f27cd30 | c4341d1d | agrees |
| 3 | Week 5 - Lab | 11 | 0f27cd30 | c4341d1d | agrees |
| 4 | Week 5 - Lab | 17 | 0f27cd30 | c4341d1d | agrees |
| 5 | Week 4 - Data Persistence and Schema Design | 1 | 1c7974a2 | 89fec97a | agrees |
| 6 | Week 4 - Data Persistence and Schema Design | 7 | 1c7974a2 | 89fec97a | agrees |
| 7 | Week 4 - Data Persistence and Schema Design | 13 | 1c7974a2 | 89fec97a | agrees |
| 8 | Week 4 - Data Persistence and Schema Design | 17 | 1c7974a2 | 89fec97a | agrees |
| 9 | Week 5 - APIs and Network Communication | 1 | 4c98b9ce | 0fa0b475 | agrees |
| 10 | Week 5 - APIs and Network Communication | 6 | 4c98b9ce | 0fa0b475 | agrees |
| 11 | Week 5 - APIs and Network Communication | 11 | 4c98b9ce | 0fa0b475 | agrees |
| 12 | Week 5 - APIs and Network Communication | 16 | 4c98b9ce | 0fa0b475 | agrees |

**Content** is the first eight characters of the SHA-256 of the exact bytes the
passage was read from; that is the column a reader can check against their own
copy of the file. **Version** is the database row, which is created fresh on
every run, so it differs each time - the first version of this table showed
only that column, which meant nobody could reproduce it. Both are printed now.

The three decks as they stand hash to `c4341d1d`, `89fec97a` and `0fa0b475`.
If a deck is replaced, these change, and the honest reading is that the check
applies to the bytes listed here rather than to "the Week 5 slides" as a name.

The M1 criterion asks for 10 of 10; this run gives 12 of 12.

## Supporting integrity checks

From the same corpus (66 pages), at character level:

| Check | Result |
| --- | --- |
| Replacement characters (dropped glyphs) | 0 |
| Control characters (mojibake) | 0 |
| Residual double spaces after cleaning | 0 |
| Line-end hyphens needing a decision | 1, verified legitimate |

## What this does and does not prove

**Proves:** for the sampled passages, the stored text really appears on the
page and in the version recorded, as judged by a tool the pipeline does not
use. Text is not invented, dropped, or attached to the wrong page.

**Does not prove:** anything about search. The passages here were selected by
position, not by a query. Whether a search returns the right passage, and
whether the UI can display it, depends on C's retrieval work and the
end-to-end run, which is not part of this check.

**Also does not prove:** that the three abnormal documents behave correctly in
the running system. They were verified at the handler level (see
`evidence/extraction-handler.md`). Verifying them through the API and the
worker is part of the combined M1 run.

## Carried forward

- The cleaning rules did not fire on this corpus at all, so their value
  depends on the fixture corpus D is preparing. Worth a five-minute check once
  those fixtures land.
- Slide titles that wrap across several lines stay on several lines. Order and
  content are correct; this is a presentation limitation, not a correctness
  one.
- Nothing sets `file.current_version_id` yet. In this check it was set when
  ingesting; the boundary needs agreeing with A or every search result will
  look stale.
