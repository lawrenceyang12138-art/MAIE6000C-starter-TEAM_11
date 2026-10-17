# W7 Q&A

## Q1. How do you know the page number is correct?

We checked 12 sampled passages against a different PDF library across 66
pages. All 12 agreed. We also sampled 20 fragments in the parser quality check
and found all 20 on the page they claimed. Checking our own output with our
own extractor would not have been independent.

## Q2. What happens to an encrypted, damaged or image-only PDF?

It is recorded against its file version with a distinct reason code:
`encrypted`, `corrupt`, `no_text_layer` or `unsupported_format`. It does not
stop the other files in the scan. The API and UI show the reason rather than
silently dropping the file.

## Q3. What if a file changes while it is being parsed?

The parser hashes the bytes it reads and compares that hash with the hash the
scanner recorded for the version. If they differ, it refuses to publish the
text and records `source_changed`. That prevents text from one set of bytes
being shown under the hash of another set.

## Q4. Why does a repeated scan not create duplicates?

The scan identity is `(root_id, relative_path)` for the file and
`(file_id, content_sha256)` for the version. A repeated scan reuses the
existing version and checks for an active extraction job before creating a new
one. The original corpus is not modified by the duplicate test.

## Q5. How does search avoid unauthorized or stale content?

The search query joins the canonical chunks to the current file version, the
present file record and the authorized root. It only accepts `basic_ready` or
`enriched` versions, and only active or paused roots. Revoked roots, missing
files and superseded versions are excluded. Evidence reads apply the same
checks again.

## Q6. What happens if the semantic model is unavailable?

The service returns keyword results with a visible degradation reason such as
`ai_unavailable`, `ai_disabled` or `embeddings_not_ready`. It never labels a
keyword result as semantic. In this checkout the local E5 model is not
present, so the demo correctly says keyword-only.

## Q7. Why is human review append-only?

Model and rule output can be regenerated; a human decision cannot. Each review
has a revision number and the caller must supply the revision it saw. A stale
reviewer receives a conflict instead of overwriting someone else's decision.
A correction must also name the replacement entity.

## Q8. Can a failed job be retried?

Yes. `POST /jobs/{id}/retry` moves only a failed job back to `pending`,
clears the old error and keeps the attempt count. The client cannot set the
job to `running` or `completed`. A transient worker failure is also retried
automatically with bounded exponential backoff. Claims have leases, and an
expired claim is returned to `retry_wait`.

## Q9. Why are you using a separate search index table?

The canonical file, version and chunk text belongs to B's model. Search fields
are derived data and may change independently. `chunk_search_index` is keyed
by `source_chunks.id` with a cascading foreign key, so there is still one
source of truth and one stable id for search and evidence.

## Q10. How do you know the original files were not modified?

The source mount is read-only. The live scan recorded the corpus SHA-256
fingerprints before and after the run, and the difference was 0. Mutation tests
use an isolated copy, never the frozen demo corpus.

## Q11. What is deliberately out of scope?

OCR, automatic folder monitoring, DOCX/TXT/Markdown, file move/rename/undo,
cross-file answer generation, cloud fallback and a full knowledge graph are
outside the W7 slice. They are R1 or later work, not hidden requirements
dressed up as completed features.

## Q12. What is the next engineering step?

Prepare and verify the pinned local E5 model and run the five frozen semantic
descriptions offline. Then load-test multiple competing workers and the lease
recovery path. The final presentation materials must be frozen against the
same commit SHA and release manifest.
