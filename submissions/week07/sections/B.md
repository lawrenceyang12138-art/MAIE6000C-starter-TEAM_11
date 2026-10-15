# B - Read files: parsing, evidence and relations

## 1. Scope

This workstream owns everything between "a file exists on disk" and "a passage
can be shown to a user with a page number they can trust". Concretely: text
extraction, chunking and page mapping, the evidence read path, the minimum
entity candidates with their supporting quotes, and the human review that sits
on top.

Two boundaries were kept deliberately. A owns the worker dispatch loop and the
HTTP routes, so nothing here is wired into either yet; the handlers are called
from tests and scripts. A also owns the shared schema, so the four tables this
workstream needed were added as a working proposal with a migration rather than
as a description for someone else to interpret.

## 2. The pipeline

Seven functions, in the order the worker will drive them:

```
extract_document(path)            per-page text plus the file's content hash
chunk_document(document)          located, overlapping chunks
persist_chunks(db, version, ...)  store them against a file version
candidate_relations(chunks)       entity candidates, each with its quote
persist_relations(db, version, ...) entities, relations and evidence
read_evidence(db, chunk_id)       serve a passage, or refuse if stale
read_relationships(db, version)   bounded relation list for display
record_review(db, relation, ...)  append a human decision with a revision
```

## 3. Design decisions worth defending

**A chunk never crosses a page boundary.** The page is the citation unit, so
"page 7" has to be exactly true for every chunk stored on page 7. The cost is
accepted deliberately: a long page produces several chunks sharing one page
number, and a short page produces a short chunk. The alternative - letting
chunks span pages for better semantic continuity - would make the page number
ambiguous and undermine the one thing the interface promises.

**Chunks are replaced; relations are not.** Re-processing a file version
replaces its chunks, because a version is identified by its content hash and a
parser upgrade should supersede the old text. Entities and relations are
instead found-or-created, so a relationship keeps its row id across re-runs.
That difference exists for one reason: a human review points at a relationship,
and replacing the row would silently discard the review with it.

**A bad document is an ordinary outcome.** Encrypted, damaged and image-only
files are recorded against the version with a specific reason code and returned
normally, so one unreadable file cannot stop a scan. Verified by running a
corrupt file and then a good one through the same handler: the good file still
reaches `basic_ready` with its chunks stored.

**A file that changed while being read is not published.** Extraction returns a
hash of what was actually read. If it differs from the hash the version was
created with, the chunks are discarded and the version is marked failed with
`source_changed`. Publishing in that case would attach text from one set of
bytes to a version row that claims different ones.

**Evidence is not optional.** A relation cannot be stored without the passage
that justifies it, and citing a chunk that has not been stored raises rather
than writing an uncheckable claim. The same rule shapes the evidence read path:
a passage is only served while its version is still current, its file is still
present, and its folder authorisation is still active.

**Review is append-only behind a revision guard.** A decision is appended with
the next revision number rather than overwriting the previous one, and the
caller must pass the revision it last saw. Two people reviewing at the same
time therefore produce a visible conflict instead of one silently discarding
the other's decision. Human decisions are the only thing in this system that
reprocessing never regenerates, so they are stored to outlive everything
derived from them.

## 4. Problems found and fixed

**A false alarm worth recording.** An early read of the course slides showed
slide titles interleaved with body text, which looked like a parsing defect.
Checking the artefact the pipeline actually produces showed the opposite: the
titles come out as consecutive lines in the correct order. Two other extraction
backends were tested on the same page and both interleaved it, so the reading
order of the chosen backend is a genuine advantage. The lesson is recorded
because the wrong conclusion nearly went into the documents.

**Person detection never matched.** The rule checked whether the twelve
characters before a name were a title, but that window contained text from
before the title, so it never matched. It now anchors to the end of the
preceding text. Without the test this would have shipped as "we find no
people".

**An unsupported file reported the wrong reason.** A plain text file was
reported as a corrupt PDF. It is not a broken PDF, it is a file type we do not
handle, and the difference matters because the acceptance criterion requires an
unsupported file to keep a record with a truthful reason. The extractor now
checks the PDF header and reports `unsupported_format`.

## 5. Honest limitations

**Entity finding is a rule, not a model, and it is roughly three in four
precise.** On real slides the rules first produced 47 candidates, most of them
sentence openers. Skipping line-initial single words took that to about 33;
ranking by mention count and bounding the list to ten left lists that a person
would recognise, with residual noise such as `Which` and `Who`. That is usable
for a candidate list a human reviews, and not usable as automatic fact
extraction.

**The cleaning rules did not fire on our corpus at all.** Zero hyphen joins,
zero Chinese-space removals, zero headers removed across 66 real pages. The
rules are tested with synthetic input and are not wrong, they are simply not
needed by these files. Whether they matter depends on the fixture corpus, which
is worth a five-minute check when it lands.

**A person's title is not part of their label.** `Dr. Chen` is stored as
`Chen`; the quote preserves the title. Titles are used for classification, not
for the label.

**No layout reconstruction.** Text inside tables keeps whatever order the PDF
produced, and a wrapped slide title stays on several lines. Order and content
are correct; reflowing them is out of scope.

## 6. What is not done

- No HTTP endpoints. Every capability above exists as a handler only.
- Nothing calls these handlers from the worker yet.
- Nothing sets `file.current_version_id`, so every evidence read currently
  reports the passage as stale until that boundary is agreed with A.
- No evaluation against the official fixture corpus, which has not landed.

## 7. Evidence index

| Item | Where |
| --- | --- |
| Parsing baseline, three real PDFs and three abnormal fixtures | `evidence/parsing-baseline.md` |
| 20 sample chunks with a page-attribution check | `evidence/chunking-samples.md` |
| Chunk policy and its limits | `submissions/week07/chunk-policy.md` |
| Write-back, including the repeated-write check | `evidence/chunk-persistence.md` |
| Handler and failure isolation | `evidence/extraction-handler.md` |
| Evidence read path and staleness refusals | `evidence/evidence-read-path.md` |
| Quality check across 66 pages | `evidence/pdf-quality.md` |
| Independent page-attribution check, 12/12 | `submissions/week07/m1-evidence.md` |
| 12 normal / 3 abnormal / 1 unsupported regression | `submissions/week07/B-fixes.md` |
| Entity candidates and the precision finding | `evidence/relation-candidates.md` |
| Bounded relation read and review revisions | `evidence/relation-review.md` |
