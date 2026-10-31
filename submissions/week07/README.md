# Team 11 — Week 07 midterm milestone

Audit date: 2026-10-31. Branch: `feat/c-team-pdf-evaluation`.
Code-inspection baseline: `0e3d715`, before the current fixes and rerun.

The W7 workflow is implemented and its **18 automated acceptance gates pass**
across the API, Worker, parser, search and frontend. This audit fixed defects and
tested the resulting working tree before committing it, using real PostgreSQL,
built Linux images, the pinned local model and an independent browser. The
verified changes were subsequently committed by topic; the repository owner
will handle the remote push. See the
[acceptance matrix](../../docs/w7-acceptance.md) and
[current evidence index](evidence/20261031-w7/README.md).
Human gold review and team signatures remain separate; none are supplied here.

Roles: A owns authorization, scanning, durable jobs and assembly; B owns parsing,
evidence, relation candidates and reviews; C owns retrieval, model preparation
and evaluation; D owns the browser workflow and milestone materials.

## 1. Verified workflow

A user selects a directory beneath an allowlisted read-only mount. The API stores
an authorized root and pending scan job atomically and returns 202. The Worker
scans subfolders, records immutable content versions, extracts page-bound chunks,
automatically stores rule-based person/project/topic candidates and indexes the
text. Search supports keyword, semantic and hybrid modes; each hit resolves to
its canonical chunk evidence. The relation/review screens consume direct chunk
IDs and persist revisioned confirm/correct/reject decisions.

The first-start launcher prepares the pinned local PPLX model, exposes real setup
progress and retry, and queues missing document embeddings when the model becomes
ready. Keyword search and evidence remain separate capabilities from semantic
readiness. First-import keyword sidecars are published atomically with parsed
chunks, so a newly ready document is searchable before AI indexing completes.

## 2. Live demo sequence

| Beat | Action | Observable result |
| --- | --- | --- |
| Input and durable acceptance | Open `/select`, choose an allowlisted directory and authorize | Real 202 response with root/job IDs; persisted root and pending scan job |
| Async processing | Open progress and wait for file stages | Scan/extract/embed jobs, current file counts and safe abnormal reasons |
| Persisted output | Search a cross-folder keyword, then semantic/hybrid; open a hit | Requested/effective modes, matching file/version/page/chunk and source passage |
| Human correction | Open relations and review a source-backed candidate | Direct evidence, saved decision revision and explicit stale-revision conflict |
| Failure and recovery | Disconnect AI; exercise a recoverable failed source job | Visible keyword fallback; explicit retry with retained attempts |
| Durability and operations | Restart normally; reread IDs and inspect health/metrics | Same data/reviews, database readiness, counters and unchanged source hashes |

All three scenarios passed against real services. First import used a new empty
database with AI disabled; repeated scans preserved canonical IDs and queued no
new extraction/embedding work. Mixed import reported twelve ready documents and
four handled unsupported inputs. The review browser saved all three decisions
and verified persistence after reload. The dedicated demo is available at
`http://127.0.0.1:13001` while the audit stack is running.

## 3. Current implementation status

Implemented: canonical files/versions/chunks and one migration chain; scanning
and current-version pointers; stable chunks; durable jobs and explicit retries;
PDF text extraction and abnormal reasons; automatic bounded relation candidates;
source identity checks; revisioned append-only reviews; keyword/semantic/hybrid
search and degradation; real API-mode UI; local model preparation and recovery
indexing. New frontend builds default to API mode; an existing explicit mock
configuration remains a labelled simulation.

Repairs verified in this run include direct relation chunk evidence and correction
selection; review receipt validation; safe unreadable-source refusals; missing
first-index dispatch recovery; no AI calls with embeddings disabled; atomic
keyword readiness; local Host/Origin protection; AI-independent cold startup;
complete sidecar migration rollback; and packaged frozen evaluation inputs with
graceful Git-unavailable reporting. The verifier now allows completed model-recovery
indexing history while retaining strict rescan and live-job checks.

Later scope: filesystem watcher, OCR, other document formats, complete graph
traversal, multi-worker leases/backoff, export/purge and all file organization.
A crash during a claimed job currently has no lease recovery; explicit retry of
an ordinarily recorded failed job is supported.

## 4. Architecture status

Five Compose services form the application: frontend/nginx, API, Worker, local
AI and PostgreSQL/pgvector. API and Worker read the same source mounts read-only.
The AI service alone can write its model cache. The source-of-truth tables are
`authorized_roots`, `files`, `file_versions`, `source_chunks`, jobs, entities,
relationships, relation evidence and reviews. Search sidecars contain derived
keyword/token/page metadata and retain the canonical chunk/version identities.

The [shared contract](../../docs/team11-w7-shared-contract.md) defines current
routes and semantics. The Week 4 proposal defines the W7 scope; later draft
routes and future queue architecture are distinguished in the acceptance matrix.

## 5. Evidence of integration

| Evidence | Scope |
| --- | --- |
| [Current acceptance matrix](../../docs/w7-acceptance.md) | Requirement sources, test entries and current-run results |
| [2026-10-31 evidence](evidence/20261031-w7/README.md) | Final commands, 18-gate results, image/tree identities, real browser/API/DB/model/restart reports and preserved failure-to-fix records |
| [B pipeline and relation evidence](evidence/B/README.md) | Historical real Compose/API/Worker and direct relation/review checks |
| [C navigation evidence](evidence/C/20261030-page-navigation/README.md) | Historical local-model SQLite/PostgreSQL evaluation and HTTP recovery |
| [C startup evidence](evidence/C/20261030-startup/README.md) | Historical first-start verification; retain its stated limits |
| `evidence/1016-D/`, `evidence/1019-D/` | Historical intercepted HTTP-contract and explicit mock browser checks; not product acceptance |
| [M1 checklist](m1-checklist.md) | Three real scenarios and human sign-off status |

## 6. Testing and verification

Original integrated run's rebuilt Linux image: **744 Python tests passed, 0 skipped; Ruff clean**,
including real PostgreSQL/pgvector and five migration tests. Frontend: **56 Vitest
and 56 Node contract tests passed** in that snapshot, production build passed. The
[current CI Node follow-up at `2b975a0`](evidence/20261031-w7/node-review-followup.json)
passed **62/62 tests** (56 contracts plus 6 browser-launcher regressions;
[output](evidence/20261031-w7/node-review-followup.tap)). Fixture and mock
adapter validation passed. Frozen source-location checks verified 10/10 locations
and 16 file hashes; these are source checks, not a retrieval-quality result.

Real HTTP/DB: 202 checks/0 failures both with AI absent initially and after final
rebuild. Safety/independent physical pages: 102 checks/0 failures, 30/30 chunks.
Real browsers: empty-DB import/search/rescan 3 cases, fresh-root 3 cases, mixed
import/reviews 6 cases; fixture contract 19 and explicit mock 5 are recorded
separately. Real model ready/disconnected/restored modes, setup retry and normal
container recreation all passed. PostgreSQL is 16.15 with pgvector 0.8.7.

The model startup run verified/reused the existing fixed cache and executed native
inference; it did not repeat model downloading. Windows' earlier two platform
skips (symlink privilege/FIFO) both execute successfully in Linux. Historical
222/230/530/587/737/741 counts retain their dated identities and are not final totals.

`scripts/w7_evidence_probe.py` is a scan probe. Its older output only compares
file totals/stages; use persisted IDs and DB counts to prove version/chunk/job
idempotency rather than inferring it from unchanged UI counters.

## 7. Risks and revised scope

The former missing-route, missing relation `chunk_id` and unspecified review
response blockers are closed. The current run also closes the implementation and
testing blockers for the combined tree and local request/startup boundaries.
Two different historical corpora remain documented: D's frozen abnormal manifest has obsolete
status/code expectations; B's live mounted corpus uses the parser's actual
`corrupt`, `encrypted`, `no_text_layer`, `unsupported_format` taxonomy. Preserve
old answers and bytes; a unified acceptance manifest needs its own version.

Human gold review and A/B/C/D milestone signatures remain explicit human tasks;
automated implementation and verification do not supply those signatures.

## 8. Plan from Week 7 to Week 13

The W7 implementation and automated verification are complete. Subsequent work includes queue leases
and crash recovery, monitoring, scope management/export, additional formats/OCR
and broader graph exploration. Move/rename/undo remain stretch capabilities.

## 9. Artifact index

- [Acceptance matrix](../../docs/w7-acceptance.md)
- [Report and historical freeze record](report.md)
- [M1 checklist](m1-checklist.md), [scope decisions](scope-decision.md)
- [Demo script](demo-script.md), [architecture](../../docs/architecture.md), [operations](../../docs/operations.md)
- [Shared contract](../../docs/team11-w7-shared-contract.md), `evidence/`, `sections/`
- [AI use statement](ai-use-statement.md)

## 10. AI use statement

AI assisted the requirement audit, implementation review, bug fixes, test execution
and documentation. Claims of successful execution require recorded command output
and evidence. No human gold review or teammate approval is generated on behalf of
another person. Earlier disclosures remain in their dated evidence records.
