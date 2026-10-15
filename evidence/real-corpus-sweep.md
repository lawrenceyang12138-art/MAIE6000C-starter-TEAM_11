# Real corpus sweep: the parser against documents it has never seen

Owner: B (read files). Run on 2026-10-15.

## Why this exists

Everything else in `evidence/` is measured on the three course decks, which
come from one producer in one style. A parser that has only ever met those is
not tested; it is familiar. So the extractor was pointed at every PDF on this
machine - other courses' lecture notes, exported slides, syllabi, a paper, this
team's own schedule - and told to read all of them.

## Result

```
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "/path/to/documents:/corpus:ro" api \
  python scripts/sweep_corpus.py /corpus
```

| | |
| --- | --- |
| Documents | **38** |
| Pages read | **1,723** |
| Characters extracted | **783,267** |
| Read successfully | 38 |
| Refused with a reason code | 0 |
| **Crashed** | **0** |

1723 pages without a single unexpected exception is the point of the sweep: a
file that makes the extractor raise would make the worker fail the whole job
instead of recording why that one document could not be read. None did.

**The totals belong to the folder as it was that afternoon, not to a fixed
corpus.** The sweep reads whatever PDFs are on the machine, so adding two
documents changes the page count without anything in the parser changing. Re-run
two documents later, on 40 files: **1,822 pages, 40 read, 0 refused, 0
unexpected, 49 unreadable glyphs, 0 control characters stored** - the same
outcome, larger totals. What the script actually asserts is the last column of
that sentence, not the size of the pile: **no crashes, no unrefused documents,
nothing unreadable left as a control character.** A reader who re-runs it and
sees different totals has not found a contradiction; a reader who sees a
non-zero exit code has.

## What the sweep found

### 1. Symbols whose font encoding has no Unicode mapping

Two documents - `05_Vector_Space_Models.pdf` and `notes_03.pdf`, both from
another course - arrived with **19 C0 control characters** in their text, where
a radical sign and stretched brackets belong. Neither file is in this
repository: they are other courses' teaching materials sitting in the
presenter's own folder tree, and the script names every file it reads so the
list is reproducible on the machine that has them rather than invented:

```
IDF(t)= log
\x10
total documents
documents containing t
\x11
```

That is `log(√(total documents / documents containing t))`, with the radical
split across two codes the font maps to 0x10 and 0x11.

Installing `fontTools`, which pypdf asks for when it meets a CFF Type1 font,
**did not change it**. The mapping is simply missing from the document, so this
is a property of the file rather than a missing dependency.

Left alone, those characters are invisible in the interface, match nothing in
a search, and travel through JSON as control codes. `clean_page_text` now
replaces C0 control characters other than newlines and tabs with **U+FFFD**,
the standard "something was here and could not be read" marker. Measured after
the change, over the same 38 documents: **19 unreadable glyphs in the raw text,
0 control characters in the stored text, 20 marks where they were.**

The mark count is one higher than the glyph count for a boring reason worth
writing down: chunks overlap, so a glyph that sits inside the overlap appears
in two chunks and is counted twice. The script says so rather than leaving the
next reader to wonder.

This is the honest version of the claim: not "we never lose a glyph", but "a
glyph we cannot read is marked where it was, not silently dropped".

### 2. A document can pass the text-layer check and still be nearly empty

`MAIE Lecture Sep 2026.pdf` is 32 pages with **382 characters of text** - about
twelve characters per page. It is an image-heavy deck with a thin text layer,
so it is not refused: the check is per document, and at least one page has
text.

The consequence is worth stating before someone discovers it on stage: the
parser reports success, and what the user gets from those 32 pages is almost
nothing. A per-page density check would be the fix, and it is not in this
slice. The full-scan case *is* handled - a document with no text at all is
refused with `no_text_layer`.

## What this does not prove

- **Not accuracy of meaning.** The sweep counts characters and crashes; it does
  not check that the text is a faithful reading of the page. That is what
  `verify_page_attribution.py` does, on a smaller sample.
- **Not a benchmark.** 38 documents from one laptop is a smoke test at scale,
  not a corpus anyone chose. The fixtures D is preparing remain the real test.
- **Not scanned documents at scale.** This pile contains one near-scan, not a
  set of them.
