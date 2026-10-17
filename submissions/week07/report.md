# Team 11 — W7 Midterm Technical Report

## Executive summary

Team 11 is building a local-first, read-only file retrieval assistant. The W7
goal is not a general document chatbot. It is a narrow vertical slice in which
a user authorizes a folder, the system asynchronously discovers and parses its
files, a keyword query returns a current passage, and the user can open the
same passage with its file, version and page number.

The integration branch implements that slice. On a fresh PostgreSQL database,
the fixed corpus produced 16 files and 16 versions: 12 normal PDFs became
searchable and 4 abnormal or unsupported records retained explicit reasons.
The five frozen keyword queries returned the expected file and page 5/5, and
opening each returned chunk produced matching evidence 5/5. A repeated scan
created no duplicate files or versions. The browser walkthrough selected the
authorized root, observed the 16/16 scan, searched for a known phrase, and
opened the P1 evidence for `team11-demo-01.pdf`.

The system is deliberately honest about what is not finished. Semantic
retrieval is now real, not structural: the pinned E5 model produced 20 vectors,
and the frozen S01–S05 descriptions hit the expected file/page 5/5 with
evidence 5/5. The model directory is intentionally outside Git and must be
copied into the release bundle. The worker has bounded automatic retry, a
claim lease and stale-claim recovery in addition to the explicit retry
endpoint; competing-worker load still needs a dedicated test.

## 1. Product and W7 scope

The target user remembers what a document meant rather than its filename.
Existing filesystem search is useful when the user knows a word; it is weak
when the user remembers a person, a project or an idea. The proposed product
adds an index over user-authorized folders while leaving the original files
untouched. It returns evidence, not a generated answer.

The W7 slice is intentionally narrower than the eventual R1 product:

- authorize a configured local folder;
- scan it in the background;
- parse text-based PDFs;
- preserve page-located chunks;
- search the current content;
- return a file, version, page and passage;
- show failures instead of silently omitting bad files.

OCR, automatic folder monitoring, non-PDF formats, document rewriting and a
full knowledge graph are outside this milestone. The user journey is:

```text
choose root
→ API returns 202 with root_id and job_id
→ worker scans and creates extraction jobs
→ parser stores page-located chunks
→ search reads only current authorized chunks
→ UI opens the version-bound passage
```

The fixed acceptance corpus has 12 normal PDFs in two subdirectories, 3
abnormal PDFs and 1 unsupported DOCX. The acceptance criteria are not “every
file parsed.” They are “the normal files are searchable, the abnormal files are
explained, and the original files are unchanged.”

## 2. Architecture and ownership

The application keeps the course starter's architecture: FastAPI, PostgreSQL,
a separate worker process, an internal AI service, Alembic and Docker Compose.
The important integration decision is that there is one canonical content
model. B's `files`, `file_versions` and `source_chunks` tables own identity,
versioning and text. C's search fields are derived data in
`chunk_search_index`, keyed by `source_chunks.id`; there is no second file
catalogue.

A owns the read-only mount allowlist, path containment, scan transaction,
current-version pointer, job dispatch and public route assembly. B owns
extraction, chunking, evidence, relation candidates and review. C owns
tokenization, ranking, optional embeddings and evaluation. D owns the browser
surface, real API adapter and acceptance evidence.

The API returns a flat `root_id` and integer `job_id` with status `pending`.
The database's internal `claimed` state is presented as `running`. The client
never sets worker-owned states. This separation matters: a successful scan job
is not the same thing as a fully parsed corpus, so the root response carries
file-stage counts rather than treating “scan complete” as “search ready.”

## 3. A — Scanning, versions and durable work

The scan service starts from an allowlisted mount. A root is a relative path
inside that mount, not an arbitrary host path. The resolver rejects absolute
paths, `..` segments, symlink escapes and files outside the authorized root.
The Docker source mount is read-only, so the product cannot modify an original
even if a later code path tries.

The scan transaction walks the root without following symlinks. For each file
it records the relative path, opens the file read-only, computes a bounded
SHA-256 identity and records the byte size. The file row is stable across
content changes; a separate `file_versions` row represents each immutable
content hash. The scanner updates `current_version_id` only when it has a
newer content version. Repeating the same scan reuses an existing version,
does not create a duplicate file and does not enqueue another extraction job
for a version already being processed.

This is not merely a performance optimization. Search and evidence must agree
about what is current. If the scanner and the parser independently guessed
which version was current, a result could point at old text while claiming to
be the user's current file. Keeping the pointer in the scan transaction gives
the rest of the system a single answer.

The worker loop claims a durable job, increments its attempt count, records a
claim timestamp, invokes a bounded processing function and persists a terminal
result. It handles two product job types in this slice: `scan_root` and
`extract_file`. A scan job creates extraction jobs; an extraction job calls B's
parser and, after a successful parse, persists relation candidates. A file
that is encrypted, corrupt, missing or unsupported becomes a version outcome
with a reason code rather than stopping the whole folder.

The live evidence from a fresh volume is:

- `GET /mounts` exposes the configured `corpus` mount as read-only;
- `POST /roots` returns 202 before discovery or parsing starts;
- a completed scan produces 16 files and 16 versions;
- the root reports 12 `basic_ready`, 0 `failed` and 4
  unsupported/abnormal records with reason codes;
- a repeated scan leaves the counts at 16/16;
- the corpus fingerprints before and after the run agree.

The worker now uses `FOR UPDATE SKIP LOCKED` on PostgreSQL, which prevents two
workers from claiming the same pending row in the normal competing-worker
case. The API also exposes `POST /jobs/{id}/retry`: only a failed job may be
returned to `pending`, and its attempt count is retained. The client cannot
directly set `running` or `completed`.

The worker now implements the Week 6 reliability increment: a bounded retry
policy with exponential backoff, a lease with a worker identity, and recovery
of a claim whose lease expires. `retry_wait` is a durable state and the client
can see it. The operator-facing manual retry remains available for a failed
job whose attempts are exhausted. The remaining operational test is to run
two competing workers against the same queue and verify the lease and
`SKIP LOCKED` behavior under load.

The scan is also responsible for reconciliation. A complete scan marks every
file it observed as present and updates its last-seen time. A file that was in
the database but is no longer under the root is marked missing rather than
deleted, so its historical version can still be inspected and a returned file
can be recognized later. Search excludes missing files, while the file record
keeps enough history to explain what happened. This is a deliberate
compromise: a temporary permission error should not erase a user's index.

The scanner has to avoid duplicate extraction jobs without locking the whole
root forever. It checks for an existing pending or claimed extraction job for
the same version before creating a new one. The current version pointer is
updated in the same transaction as the file and version rows. A failed job is
not silently converted into a new version; a retry reuses the same immutable
version and creates a fresh attempt. The migration adds the root, file,
version, chunk, relation and review tables in order, and the integration
branch keeps exactly one Alembic head.

The first-import and repeated-import tests are intentionally asymmetric. The
first test checks that a folder with mixed content creates the expected
records even when several files cannot be parsed. The repeated test checks
both the database counts and the absence of new extraction jobs. A separate
test changes one file in an isolated test copy and verifies that only that
file receives a new version. The original corpus is never used for mutation
tests; the fixed demo corpus is kept immutable.

On the API side, a job is a record of work, not a promise that the work has
finished. `GET /jobs/{id}` reports `pending`, `running`, `completed` or
`failed`, plus attempts and the safe error code. A client that receives a
completed scan can still see parsing in progress, because extraction jobs are
separate. This makes the UI's “scan complete” and “files searchable” counters
compatible with the underlying state model.

## 4. B — Reading, page evidence and review

B's pipeline turns a file version into located text. It extracts page by page,
cleans extraction noise, preserves the one-based page number, and chunks within
a page. A chunk never crosses a page boundary. The cost is deliberate: a long
page produces several chunks with the same page number, while a short page
produces a short chunk. The benefit is that “page 7” is true for every passage
stored as page 7.

The chunk policy is 700 characters with approximately 120 characters of
overlap. The overlap keeps a sentence at a split point readable in one of the
neighbours. The code prefers a paragraph break, then a sentence end, then
whitespace, and only cuts inside a word when no better boundary exists.
Running headers and footers are removed only when the same edge line appears
on at least three pages, which avoids deleting genuine repeated content.

Chunks are stored against an immutable file version. Re-processing an existing
version preserves a chunk row when its ordinal, page and text are unchanged;
that preserves the stable chunk id used by evidence and search. A changed
chunk is replaced, and database cascades remove stale derived references. If
the replacement fails, the previous chunk set is rolled back rather than
leaving a version with no text.

The extractor distinguishes outcomes that a user can act on. An encrypted
file, a damaged PDF, an image-only PDF, a non-PDF and a file that disappeared
between scan and parse are not the same failure. A file whose bytes changed
while it was being read is refused with `source_changed`; publishing that text
under the old hash would make the evidence false. When the parser succeeds,
the version records `parser_revision`, `basic_ready` and its chunks.

Evidence is read through the chunk id. The read path checks that the chunk
still exists, the version is current, the file is present and the root is
still authorized. A stale version returns a conflict rather than silently
showing old text. The live M1 path proved this end to end: every keyword hit's
chunk id was used to fetch the same page and path.

The relation layer is deliberately small. It proposes bounded person, project
and topic candidates, each with a page, quote and offsets, and stores them as
candidates rather than facts. Human review is append-only: a confirm, correct
or reject decision has a revision number, and a reviewer holding an old
revision receives a conflict instead of overwriting another decision. A
correction must name the entity it points at; a correction without a target is
only a rejection with a misleading label.

The strongest parsing evidence is independent of the parser's own code:

- 12 of 12 sampled passages were found on the claimed page by a different PDF
  library across 66 pages;
- 0 corrupt characters and 0 mojibake were observed in the quality sweep;
- 20 of 20 sampled fragments were found on the page they claimed;
- the 12 normal / 3 abnormal / 1 unsupported regression passes;
- a database write failure leaves the previous chunks intact;
- a session race on review revision produces a conflict.

The limitations are also measured. Entity finding is a rule set, not a
language model, and the bounded list is approximately three in four precise on
real slides. That is useful for human review and not enough to call an
automatic knowledge graph. The parser does not reconstruct table layout, and a
near-scan with a thin text layer can look successful while yielding very
little text.

The failure taxonomy is part of the interface, not just an internal enum.
`encrypted`, `corrupt`, `no_text_layer`, `unsupported_format`, `file_missing`,
`source_changed` and `processing_failed` describe different user actions. A
user can replace an encrypted file or rescan a missing one; a corrupt file
needs a new source; an unsupported format needs a supported converter. The
version row retains the parser revision so a later parser upgrade can be
distinguished from the original run. The evidence read path refuses a
superseded version with 409, a missing chunk with 404, a revoked root with
403, and a version with no current pointer with 503, rather than returning an
empty list that looks like a successful query.

The chunk persistence tests cover the hard cases that a demo often misses:
replacing a chunk set while preserving identical row ids, rolling back a
failed insert, rejecting non-contiguous ordinals, and verifying that
relationship evidence references the same version. A separate SQLite foreign
key test makes the cascade behavior visible in the test database as well as
PostgreSQL. The relation tests check page and offset bounds, duplicate
mentions, stale reviewer revisions, and a correction that names its
replacement entity. These are relatively small features, but each one protects
the claim that a displayed quote is actually the quote that was stored.

## 5. C — Search over the canonical index

The original C branch implemented useful search algorithms but used its own
`source_files`, `source_versions` and `source_chunks` tables. Merging that as-is
would have created two competing definitions of the same document. The
integration therefore keeps the algorithms and removes the duplicate source
model.

The canonical search index has one row per `source_chunks.id`. It stores
normalized search text, tokenized search terms, an optional 384-dimensional
embedding, the embedding model id and the embedding dimensions. The chunk id
is both primary key and cascading foreign key. If the source chunk is replaced,
its derived index disappears with it.

Text normalization and tokenization are deterministic. English words are
case-folded; Chinese runs become overlapping bigrams; stop words are removed
from the search terms but the original text remains untouched. The keyword
score gives most weight to term coverage, adds a phrase bonus and a filename
match, and selects the best passage per file. File-level deduplication keeps
the result list from being dominated by many chunks from one long document.

Search filters the canonical query to current versions that are `basic_ready`
or `enriched`, whose files are present, and whose roots are active or paused.
Revoked, missing and superseded content cannot appear. The response carries
`root_id`, `file_id`, `version_id`, `chunk_id`, ordinal, page, text, reason and
separate keyword/semantic scores. The browser can therefore open the exact
chunk rather than performing a second, potentially different query.

Semantic and hybrid requests use the same canonical base. If the AI model or
vector index is unavailable, the service returns keyword results and a
degradation reason such as `ai_unavailable`, `ai_disabled`,
`embeddings_not_ready` or `partial_embeddings`. It never presents a keyword
result as a successful semantic result. The AI service exposes an internal
`/embeddings` endpoint; the local E5 backend checks a pinned model manifest
and refuses to download a different model at runtime.

The live keyword result is strong on the controlled corpus: K01–K05 hit the
expected file and page 5/5, and evidence lookup matched each chunk 5/5. The
semantic path was then run with the real pinned E5 model: 20 canonical chunks
received 384-dimensional vectors, and the five frozen descriptions S01–S05
hit the expected file and page in the Top-3 5/5. Opening each semantic hit
returned the same chunk and page 5/5. A deterministic query-intent layer
handles generic document-number and first/middle/last page hints; it is a
re-ranking aid, not a second model or an answer-table special case.

The remaining release step is packaging, not algorithm work: copy
`models/multilingual-e5-small` into the offline bundle, build the AI image with
`INSTALL_EMBEDDINGS=1`, and re-run the five descriptions with networking
disabled. The current result is a small synthetic smoke test and must not be
presented as a general semantic benchmark.

The query contract is normalized before it reaches the database: surrounding
whitespace is collapsed, an empty query is rejected, and a query with more than
the configured token limit returns 422. File and root identifiers are bounded
to the canonical UUID shape at the schema boundary. The search query does not
accept a client-supplied SQL fragment, an order-by expression, or an arbitrary
filesystem path. Keyword matching is performed against the derived
`search_terms` column, while the original text remains in `source_chunks` for
evidence and display.

PostgreSQL uses the GIN expression index over `to_tsvector('simple',
search_terms)`; SQLite remains a development and unit-test adapter and uses
the same normalized terms. The current implementation retrieves eligible
current chunks and ranks them in Python. That is adequate for the fixed
16-file corpus and makes the ranking rules directly testable, but it is not a
claim of large-corpus performance. The `search_max_candidates` setting bounds
the candidate pool, and the result selection keeps one best passage per file
so a single long document cannot flood the visible list.

The semantic path is intentionally separable. The `EmbeddingBackend` protocol
allows a deterministic test backend, a local E5 backend, or an HTTP client.
The local backend verifies a model manifest and refuses to download a
different revision. The HTTP client validates the response model, dimensions
and vector norms before writing anything. If any batch fails, the complete
version's vector publication is abandoned; the text index remains usable.
This is why a missing model produces a degradation, not a broken search page.

The live benchmark is not a semantic quality score. It proves the file/page
contract for five keyword queries and demonstrates the fallback. The later
semantic evaluation must report the actual Top-3 results for the five
description queries, the model revision and the hardware, and must not be
retuned after seeing the expected answers. The current test suite includes a
controlled semantic backend so a future integration change cannot silently
skip the canonical chunk index.

## 6. D — Browser surface and acceptance

The browser is a React/Vite application served by Nginx in Docker. It defaults
to the real HTTP adapter; mock mode is an explicit build-time switch and is
labelled as simulated data. The adapter checks the actual 202 acceptance
contract, validates the flat root and integer job identifiers, and preserves
unknown counters instead of substituting zero. It uses bounded request
timeouts and translates structured service errors into user-facing states.

The directory page separates root authorization from scan progress. A user
chooses an approved mount and a relative directory, sees that the request was
accepted, and is taken to a job page. The job page polls the committed status
and shows processed, pending, searchable, failed and unsupported counts. It
does not claim that a completed scan means every file has been parsed.

The results page calls `POST /search` with the selected root and keyword mode.
The UI shows the reason for each match and labels each file with a searchable
or attention state. Selecting a result opens an inspector with the version id,
relative path, page and exact stored passage. The inspector fetches evidence
by chunk id and refuses to display a result if the file, version or page does
not match. A stale or unavailable source is shown as an error rather than as
an empty result.

The browser acceptance run used the real services:

1. The `corpus` mount was selected and the root was authorized.
2. Job 19 showed 16 of 16 files processed, 12 searchable, 0 failed and 4
   unsupported.
3. Search for `Team 11 synthetic document 01` returned
   `normal/team-alpha/team11-demo-01.pdf` as the top result.
4. The result showed `keyword: team, 11, synthetic, document, 01; phrase
   match` and page 1.
5. The inspector showed version
   `f3ec6956-c50f-4b50-a3d8-f1bd02ffd5e0`, page P1, the relative path and the
   stored passage `Team 11 synthetic document 01 | synthetic page 1 of 1`.

This is the first point at which the browser path is backed by the real API,
real PostgreSQL, the real worker and the real parser. Earlier D screenshots
were contract screenshots with watermarks and were explicitly not product
acceptance evidence.

D's automated checks cover adapter validation, empty and failed states,
unknown counters, source-unavailable handling and keyword-only degradation.
The frontend test record reports 11 Vitest tests and 35 Node integration/mock
tests, and the production build succeeds. These checks do not replace the
human browser run; they protect the contract and the render path around it.

The failed-job screen now exposes a retry control. It requeues only a failed
job and starts polling again; it cannot set a worker-owned state. The remaining
D work is formal packaging: attach the acceptance screenshots to the
submission, finish the final recording and rehearse the six-step demo. The UI
now has a verified semantic mode locally, while retaining an explicit
keyword-only degradation when the model is unavailable.

The adapter is deliberately strict. It requires an HTTP 202 for root
authorization, an integer job id, a flat root id and a recognized job state.
It does not silently fall back to demo data when the API is unavailable. The
directory selector is populated from `GET /mounts` and
`GET /mounts/{id}/directories`; an unknown mount or an unsafe relative path
is rejected before a request is sent. A repeated scan receives the
`active_job_exists` conflict rather than generating duplicate jobs.

The progress page keeps the root's file-stage counters separate from the scan
job's processed count. This avoids the misleading statement “100% complete”
when a scan has enumerated files but extraction jobs are still pending. The
results page presents empty, failed, unsupported, source-unavailable and
keyword-only states as different messages. It stores the selected root only
in session storage and does not put an absolute host path in the URL or the
browser response.

The acceptance evidence is intentionally plain. The UI shows the root id, job
id, search reason, page label, file path and version id in the same view, which
lets an auditor compare the screen with the API and database without reading
the source code. The browser run was performed against the real services, not
the mock adapter. The earlier watermarked contract images remain useful for
layout regression, but are not counted as product acceptance evidence.

Accessibility and responsive behavior are partially checked: the browser
surface uses semantic headings, buttons and fields, and the DOM exposes the
search field, filters and result controls. This is not yet a full WCAG audit.
The final demo should use one stable viewport, a clean database, and the same
16-file corpus that was frozen for M1.

D's risk register has three active items. First, the UI can look more complete
than the data because a result list renders even when only keyword search is
available; the telemetry line must continue to disclose the effective mode.
Second, the evidence inspector is only as trustworthy as the adapter's
version check; the inspector therefore validates the returned file, version,
path and page before rendering a passage, and hides a cached passage when the
source is unavailable. Third, the demo must not be performed against a mock
or a stale screenshot. The final checklist should record the real URL, root
id, job id, query, expected file/page and the corresponding API response.

The D handoff also includes the material assembly responsibility. The
acceptance ledger should contain one row for each browser scenario, not only a
single successful screenshot. Each row needs the database cleanliness state,
the root and job ids, the visible counts, the query, the first result, the
evidence page and a link to the artifact. A reviewer should be able to
reproduce a row without reading the source code. The current browser evidence
file records the first/repeat scan and search/evidence path; the screenshot
and the remaining scenario rows still need to be attached to the final
submission package.

For the final presentation, D should demonstrate the normal path first and
then one deliberate failure. The normal path proves the product value; the
failure path proves that an unsupported file or unavailable semantic service
does not turn into a fabricated result. The twelve-slide deck should leave
technical design to A/B/C and use D's three slides for the user journey,
acceptance evidence and limitations. This division keeps the presentation
faithful to the work rather than making the interface appear more capable than
the measured system.

## 7. Integration evidence and failure boundaries

The integrated test suite reports 139 passed and 1 skipped; the skip is the
starter smoke test that needs a live `SMOKE_BASE_URL`. `ruff check .` is clean.
A fresh PostgreSQL database reaches one migration head. The live 16-file run
produces 16 files, 16 versions, 20 chunks and 20 derived search-index rows.

The most important boundaries are tested by negative cases:

- a path outside the allowlisted root is rejected;
- a symlinked directory is not traversed;
- an unknown mount is rejected;
- a missing file becomes a recorded reason, not a silent omission;
- a changed source is not published under the wrong hash;
- a stale version's evidence is refused;
- a revoked root is excluded from search;
- a malformed query or unsupported mode is rejected;
- a failed job can be retried only explicitly;
- a stale review revision produces a conflict.

These are the places where a demo can look correct while the product is
unsafe. The system therefore favors visible failure over a plausible but
unverifiable result.

## 8. Risks and scope decisions

The highest product risk is semantic overclaiming. The five semantic queries
are a synthetic smoke test, not a general quality benchmark; the release must
keep the model revision and query set with the result. The second risk is
operational: the single-worker lease path is implemented but not yet
load-tested with competing workers. The third risk is material completeness:
the code and evidence are ahead of the final recording and second-computer
verification.

The current scope cut is explicit: no OCR, no automatic monitoring, no file
operations, no cross-file answer generation and no full graph. The system
still preserves the two core promises: users can find a passage by content,
and every result is traceable to a current source version and page.

## 9. Plan to the final demonstration

Before the M1 gate, the team should freeze the keyword path and collect the
three browser scenarios with task ids and screenshots. After M1, the priority
is to package the prepared semantic model for offline execution. In parallel,
D should finish the acceptance package, the team should review the drafted
report, ten-section README, 12-page deck, six-step script and Q&A, and A should
load-test competing workers.

The final release should point to one commit SHA and one manifest. The
demonstration should use the real local stack; the recording is a backup, not
a substitute for the product path.

## 10. AI Use Statement

The team used an AI coding assistant for scaffolding, tests, debugging,
evidence scripts and document drafts. The detailed disclosure is in
`submissions/week07/ai-use-statement.md`. Every member must review and sign
their own section. The report deliberately records model packaging,
unfinished competing-worker load testing and the missing recording as open
work rather than turning them into claims of completion.
