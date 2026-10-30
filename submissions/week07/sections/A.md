# A - Finding Files: Authorization, Scanning and Durable Jobs

## Scope

The "find files" workstream owns the boundary between a user-authorized folder
and the rest of Team 11's product. It does not decide how text is parsed or how
results are ranked. It answers a smaller and more important question: which
files exist, which immutable content version is current, and what durable work
must happen next?

Everything starts from an allowlisted source mount. A root is a relative
directory inside that mount, never an arbitrary host path. The resolver rejects
absolute paths, parent traversal and paths that leave the root after
canonicalisation, and traversal never follows symlinked directories. The
Compose volume is mounted read-only, so a defect in the scanner cannot mutate
the user's corpus.

## Scanning and identity

For each discovered file the scanner records the relative path, name, byte size
and SHA-256. The file row is stable across content changes; the content hash is
what creates a new `file_versions` row, and only when the bytes actually
differ. Discovery does not filter by extension: whether a document can be
parsed is decided by extraction, so an unsupported file stays visible as a
record with a reason instead of disappearing.

The scan transaction sets `files.current_version_id` and enqueues an
`extract_file` job together, because the pointer means "latest content observed
on disk", not "latest content parsed". When a scan meets content it has already
recorded, it reuses that version row; it only re-dispatches a version that was
never processed and has no live job. A `failed` or `unsupported` version stays
on the explicit retry path rather than being re-queued by every scan.

One case needed correcting during review, and it is worth naming because it was
the worst failure mode we had: after a file was edited and then reverted, the
scan reused the old version but left the pointer on the revised one. Evidence
for the version actually on disk answered `409 version_superseded`, while
evidence for the superseded version answered `200` with text the file no longer
contained. Serving stale text as current contradicts the whole point of keeping
versions. The fix moves the pointer back to the observed version and still
creates nothing, so idempotency is preserved.

A file the scan can no longer read is kept, not dropped, and the state says
which of the two things happened. `missing` means the walk covered its directory
and the path was not there. `unavailable` means the scan could not read it: an
I/O or permission error, a link the walk refuses to follow (`not_a_regular_file`),
or a directory that could not be listed or entered (`unreadable`) - in that case
the scan has no evidence that the file is gone, so it says so. Both keep the last
observed version and pointer, and neither is counted as a deletion, so a
temporary permission failure stays visible and explainable instead of deleting
history or sending the user looking for a file that is still on disk.

## Durable jobs

`POST /roots` authorizes a folder and creates its scan job in one transaction.
It returns `202` with a flat `root_id`, an integer `job_id` and `pending`
status, and does no enumeration inside the request. That is the central
asynchronous contract: the response means "the work has been accepted", not
"the work has finished". `POST /roots/{root_id}/scans` queues another scan of
an already authorized folder and answers `409 active_job_exists` while one is
still live, so a double-click cannot start two walks of the same tree.

The worker claims a pending job, increments `attempts`, records `claimed_at`,
runs the handler and persists a terminal state. Scan jobs create per-version
extraction jobs; a successful extraction queues exactly one index job in the
same transaction, and only after the text is stored. The public API maps the
internal `claimed` state to `running`, so the browser never has to know a
database-only word, and it publishes a stable `error_code` when a job fails
instead of the diagnostic string, so exception text and container paths cannot
leak into the client. A document's own reason stays on the version, where
`GET /files` shows it; a completed job carries no code.

`POST /jobs/{job_id}/retry` accepts only a failed job, refuses when another job
is already working on the same target, returns the job to `pending`, clears the
recorded error and keeps the attempt count as provenance. A damaged or
encrypted document is not a failed job at all: it is a completed outcome
recorded on the version as `unsupported` with a reason code, which is why the
queue in the demo is empty of failures.

## API and data model

The canonical tables are `authorized_roots`, `files`, `file_versions` and
`source_chunks`. B owns the text in `source_chunks` and its evidence route; A
owns the root/file/version relationship, the scan transaction and the job and
mount assembly. The migration chain has a single head and is applied by the API
container on start.

Root responses carry stage counts - total, discovered, extracting,
`basic_ready`, enriched, failed and `unsupported` - so the browser cannot
mistake "scan job complete" for "everything is searchable". They also carry a
derived `availability`, computed from whether the authorized directory is
readable right now; storing a flag would let it lie after a mount disappears.
Error bodies follow the shared envelope, with `unknown_mount` as `404`,
`path_out_of_scope` as `403`, and `active_job_exists`, `root_revoked`,
`root_paused` and `job_not_retryable` as `409`.

## Verification

All numbers below come from the evidence documents under
`submissions/week07/evidence/`, produced by
`scripts/w7_evidence_probe.py`, which uses only public routes.

- Fresh import: a new root over `regression/` produced 13 files, 12
  `basic_ready` and 1 `unsupported` (`unsupported_format`), with 13 extraction
  jobs and 12 index jobs, all completed (`m1-catalog.md`).
- Mixed corpus: the whole 16-file mount produced 12 `basic_ready` and 4
  `unsupported` with distinct reasons - `corrupt`, `encrypted`,
  `no_text_layer`, `unsupported_format` - and no failed jobs. Bad inputs did
  not block the good ones.
- Idempotency: after eleven scans across two roots, the database held 29 files
  and 29 versions, one version per file. The job table held 64 rows with the
  highest id at 64, so the sequence has no gaps (`scan-idempotency.md`).
- Persistence: both an in-place restart and a `down`/`up` recreation returned
  the same root, the same 13 files, the same stage counts and the same
  originals' SHA-256, and the API re-applied the migration on the populated
  database without error (`restart-v1.md`).
- Security: fourteen refusal cases are covered by tests, and the originals
  matched before and after every run (`security-check.md`).
- Suite: `pytest tests/unit tests/integration -q` reports 222 passed and 10
  skipped on this branch (230 passed / 2 skipped with a PostgreSQL test database
  configured, which runs the six queue-concurrency cases); `ruff check .` is clean.

## Honest limitations

The scan is a manual request, not a filesystem watcher, and the demonstration
runs a single worker. The job table records `attempts`, `claimed_at` and an
error string, but there is no claim token, no lease, no `FOR UPDATE SKIP
LOCKED` claim and no automatic backoff - so multi-worker safety and crash
recovery are explicitly not claimed, and the 4 skipped tests include the two
symlink-escape cases that this Windows host cannot create. Those two paths are
implemented but must be re-run on Linux before the claim is made.

Two further gaps are known and left for R1: overlapping authorized roots are
not rejected yet, and route-level tests run against SQLite, so they prove the
HTTP contract rather than PostgreSQL behaviour.

The scan deliberately does not use file names as identity. Two files with the
same name in different folders stay separate records, and identical content at
two paths is two locations rather than an automatic merge - a hash never
authorizes deduplication or deletion. Move detection is not implemented; if it
is added later it must report the uncertainty instead of asserting that a
rename happened.
