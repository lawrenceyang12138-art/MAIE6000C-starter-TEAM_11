# Week 7 Submission — Midterm Milestone Demo

## Team information

- Team name: Team 11
- Repository: <https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11>
- Checkpoint tag: `w07-midterm` (to be created after team review)
- Members and ownership: A — scan/jobs/integration; B — parsing/evidence; C —
  search/evaluation; D — frontend/acceptance/materials

## 1. What currently works

The integration branch has a real vertical slice:

```text
authorize a configured read-only root
→ return root_id + durable job_id
→ worker scans files and creates versions
→ parser stores page-located chunks and evidence
→ keyword search returns the current authorized chunk
→ UI opens the version-bound passage and page
```

The fixed 16-file corpus contains 12 normal PDFs in two subdirectories, 3
abnormal PDFs and 1 unsupported DOCX. The live scan reports 16 files, 16
versions, 12 `basic_ready` and 4 records with explicit unsupported/abnormal
reason codes. Repeated scans do not duplicate files or versions, and the
original corpus SHA-256 values remain unchanged.

The search route is available at `POST /search`; evidence is available at
`GET /evidence/{chunk_id}`. The results view calls the real API, not the mock
adapter. B's parsing handler also supports entity candidates, bounded relation
reads and append-only human review revisions.

## 2. Live demo sequence

1. Open the frontend at `http://127.0.0.1:3000`.
2. Select the read-only `corpus` mount and the root directory.
3. Show the scan job: 16/16 processed, 12 searchable, 0 failed, 4 unsupported.
4. Search for `Team 11 synthetic document 01` and show the top result,
   `normal/team-alpha/team11-demo-01.pdf`.
5. Open the result inspector and show the P1 evidence: version id, relative
   path and stored passage.
6. Repeat the scan and show that the file/version counts stay at 16/16.

The exact browser acceptance record is in
`submissions/week07/evidence/m1-browser-2026-10-17.md`.

## 3. Current implementation status

### Implemented

- read-only mount allowlist and path containment;
- durable `scan_root` and `extract_file` jobs;
- SHA-256 file identity, version reuse and `current_version_id`;
- per-page PDF extraction, 700-character chunks with 120-character overlap,
  and page numbers that never cross a page boundary;
- canonical `files`, `file_versions` and `source_chunks` tables;
- derived `chunk_search_index` keyed by the canonical chunk id;
- bilingual keyword search and file-deduplicated evidence results;
- explicit failure codes for encrypted, corrupt, no-text-layer, missing and
  unsupported inputs;
- relation candidates, bounded relation reads and review revision conflicts;
- results/progress/evidence browser views;
- explicit `POST /jobs/{id}/retry` and a browser retry control for a failed job;
- bounded automatic retry with backoff, claim leases and stale-claim recovery.

### Partially implemented

- Semantic search has the adapted index, vector schema and `/embeddings`
  boundary, but this checkout does not contain the pinned local E5 model.
  The live browser therefore reports keyword-only and degrades explicitly.

### Not yet implemented

- OCR and non-PDF document parsing;
- a graph view or a production-grade relation extraction model;
- the final recording and second-computer installation record; the deck,
  README, report, QA and release manifest are now present.

## 4. Architecture status

The Week 4 split remains: FastAPI API, PostgreSQL, a separate worker, an
internal AI service, Alembic migrations and Docker Compose. The important
change is that B's file/version/chunk model is now the single source of truth.
C contributes search-only derived data through `chunk_search_index`; it does
not create a parallel file catalogue. The migration chain has one head,
`a1b2c3d4e5f6`, after the search-index migration `7f3a1b2c4d5e`.

## 5. Current evidence of integration

| Path | State |
| --- | --- |
| DB write path | **works** — 16 files, 16 versions and 20 indexed chunks in a fresh PostgreSQL run |
| API path | **works** — `/mounts`, `/roots`, `/jobs`, `/files`, `/search`, `/evidence` |
| Worker path | **works** — scan and extraction jobs leave durable completed/failed records |
| AI path | **boundary exists** — `/embeddings` returns a safe degradation when the local model is absent |
| Operational signal | **works** — job status, attempts, error/reason codes, root counts and scan timestamp |

## 6. Testing and verification performed

- Python tests: **136 passed, 1 skipped**; the skip is the starter smoke test
  that requires `SMOKE_BASE_URL`.
- `ruff check .`: clean.
- Fresh PostgreSQL migration reaches the single head `a1b2c3d4e5f6`.
- Live keyword queries K01–K05: **5/5** expected file and page.
- Live evidence after each hit: **5/5** same chunk and page.
- Repeat scan: **0** new files or versions.
- Original corpus SHA-256: **0** changes.
- Browser acceptance: 16/16 processed, 12 searchable, 4 unsupported; search
  and P1 evidence inspector both opened.
- B's independent page attribution: **12/12**; parsing quality: 66 pages, 0
  corrupt characters, 20/20 sampled fragments on their claimed page.
- `make w7-check`: checks the report/section word counts, 6-step script, 12-question
  QA, 12-slide PPTX, 12-page PDF, manifest hashes and 12/3/1 corpus.

## 7. Risks and revised scope

- **Biggest current risk:** the semantics path is structurally ready but the
  pinned local E5 model is not in this checkout; do not claim semantic quality
  from a degraded keyword result.
- **Biggest cut already made:** relations are a bounded candidate list with
  quotes, not a graph; OCR and non-PDF parsing are out of the W7 slice.
- **Biggest cut still available:** keep the M1 demonstration keyword-only and
  publish semantic evaluation as a separate increment if the model bundle
  cannot be prepared in time.
- **Operational risk:** the worker now has bounded retry, a lease and stale
  claim recovery, but the team has not yet load-tested multiple competing
  workers. The manual retry route remains available for a failed job.

## 8. Plan from Week 7 to Week 13

1. Put the pinned E5 model and optional embeddings dependencies in the release
   bundle; run the frozen semantic smoke test without network access.
2. Load-test competing workers and the lease recovery path.
3. Have A/C/D cross-review the drafted sections and complete the 12-page deck.
4. Run a second-computer install, freeze the version, record the 3–4 minute
   demo and verify the manifest SHA.
5. Move to the R1 increments: DOCX/TXT/Markdown, monitoring, OCR and richer
   review, without weakening the read-only and evidence guarantees.

Model preparation is an explicit, network-only step:

```text
pip install -e ".[embeddings]"
python scripts/prepare_e5_model.py
docker compose up -d --build ai
```

The script downloads the pinned revision and writes the checksum manifest. It
does not run in the normal request path, and the model directory is not
committed to Git.

## 9. Artifact index

- Architecture: `docs/architecture.md`, `docs/team11-w7-shared-contract.md`
- Operations: `docs/operations.md`
- M1 browser evidence: `submissions/week07/evidence/m1-browser-2026-10-17.md`
- Backend live evidence: `evidence/w7-m1-live.md`
- Parser evidence: `submissions/week07/evidence-final.md`
- Search integration: `submissions/week07/integration-c-2026-10-17.md`
- Slides 4–6: `submissions/week07/slides/B-slides.pptx`
- Demo runbook: `submissions/week07/demo-runbook-B.md`
- AI disclosure: `submissions/week07/ai-use-statement.md`

## 10. AI Use Statement

The assistant was used for code scaffolding, tests, debugging, evidence checks
and documentation drafts. The detailed member-by-member statement, including
the limits of what was independently verified, is in
`submissions/week07/ai-use-statement.md`. No claim of semantic quality is made
where the model is unavailable; the team must review and sign the remaining
member statements before submission.
