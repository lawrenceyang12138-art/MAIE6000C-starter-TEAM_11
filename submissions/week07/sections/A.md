# A — Finding Files: Authorization, Scanning and Durable Jobs

## Scope

The “find files” workstream owns the boundary between a user-authorized folder
and the rest of Team 11's product. It does not decide how text is parsed or
ranked. It answers a smaller and more important question: which files exist,
which immutable content version is current, and what durable work must happen
next?

The implementation starts from an allowlisted source mount. A root is a
relative directory inside that mount, never an arbitrary host path. The
resolver rejects absolute paths, parent traversal, symlink escapes and paths
outside the root. The Compose volume is read-only, so a bug in the scanner
cannot mutate the source corpus.

## Scanning and identity

For each discovered file, the scanner records the relative path, name, size
and SHA-256. The file row is stable across content changes; the content hash
creates a new `file_version` row only when the bytes differ. The scan
transaction updates `current_version_id` and enqueues an extraction job for a
new or retryable version. A repeated scan reuses the same version and checks
for an active extraction job before creating another one.

The scanner skips symlinked directories and hidden entries. It marks a file
missing when a successful scan no longer sees it, but it retains the historical
version instead of deleting the record. This makes a temporary permission
failure visible and recoverable rather than destructive. Search excludes
missing files; evidence reads also check presence.

## Durable jobs

The API creates a root and a scan job in one transaction. It returns
`202 Accepted` with a flat `root_id`, an integer `job_id` and `pending`
status. It does not enumerate or parse files inside the request. That is the
central asynchronous contract: the HTTP response means “the work has been
accepted,” not “the work has finished.”

The worker claims a pending job, increments `attempts`, records `claimed_at`,
invokes the handler with a finite request timeout and persists a terminal
state. `scan_root` creates per-version extraction jobs. `extract_file` invokes
the parser and persists relation candidates after a successful parse. The
public API maps the internal `claimed` state to `running`; the client never
sets worker-owned states.

The PostgreSQL claim uses `FOR UPDATE SKIP LOCKED`, preventing two workers from
claiming the same pending row. A claim records a worker identity and a lease.
The worker returns expired claims to `retry_wait` and uses bounded exponential
backoff. A manual `POST /jobs/{id}/retry` accepts only a failed job, returns it
to `pending`, clears the old error and retains the attempt count. The browser
job page exposes the equivalent retry control.

## API and data model

The canonical tables are `authorized_roots`, `files`, `file_versions` and
`source_chunks`. B owns the text in `source_chunks`; A owns the root/file/
version/scan relationship and job assembly. The migration chain has a single
head. The integration branch adds C's `chunk_search_index` after the existing
chain, rather than creating a second file model.

The root response includes stage counts: total, discovered, extracting,
basic-ready, enriched, failed and unsupported. This prevents the browser from
equating “scan job complete” with “all files searchable.” Job responses expose
attempts, safe error text, creation and completion times.

## Verification

The live M1 run used a fresh PostgreSQL volume and the fixed 16-file corpus. It
produced 16 files, 16 versions, 12 `basic_ready` and 4 records with explicit
abnormal/unsupported reasons. A repeated scan left the counts at 16/16 and
created no duplicate extraction jobs. The corpus fingerprints before and after
the run agreed.

The tests cover unknown mounts, path traversal, symlink escapes, first import,
repeated scan, one changed file and mixed abnormal input. The full Python
suite passed 136 tests with one skip; `ruff check .` was clean. The skipped test
is the starter smoke test that needs a live stack.

## Honest limitations

The current scan is a manual request, not a filesystem watcher. It runs as a
single worker in the demonstration. The retry, lease and stale-claim paths are
implemented, but a multi-worker load test is still needed before calling the
system production-ready. A crashed worker's expired lease is recovered on the
next claim cycle; the manual retry remains available after retry exhaustion.

The scan also intentionally does not use file names as identity. Two files with
the same name in different subdirectories are separate records, and the same
content copied to two paths is two locations rather than an automatic merge.
This keeps evidence paths understandable to the user. A future move detector
may link two locations, but it must mark the uncertainty instead of silently
claiming that a rename happened. The current W7 demo does not implement move
detection, which is an explicit R1 extension.
