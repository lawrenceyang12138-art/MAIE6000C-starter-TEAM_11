# W13 independent Role C evidence: PDF keyword fallback

**C result: PASS for text-layer PDF keyword only.** `C-validation.md` is attributed to **Role C (Codex)** in the evidence Role D received from the team. That is the recorded role-level sign-off, not a cryptographic signature, named human sign-off, or release approval. C ran on **2026-11-28, 13:07:02–13:07:39 SGT (UTC+08:00)**.

- Tested checkout: `e7f73d14e112031131d0383d4698d6767fea0c8c` (clean tracked state before and after). The C record identifies the verified bundle with prerequisite `7a9fa8087d304f7c126fdc290dc21a98334b7972`; its SHA-256 matches D's copy: `a3889cc45b4cdd8ca9c11375c02267b053222676378736eaa16d22d6ca61ffa4`.
- Received archive: `team11-w13-c-independent-e7f73d1-pdf-keyword.zip`, SHA-256 `dcf9f44e82205c73aa3d50be18fb394d5a50d6f6fa7208c9c2557f4cfe7b0bba`. D verified all 34 listed entry digests against `evidence/SHA256SUMS` in memory. The manifest's SHA-256 is `2bcb179f47a614a4333e391a78ae38088cbbdd5dd0df14805691b57f4461e730`; it is the only unlisted entry. The raw archive is held separately, not checked into the repository.

## Runtime and browser checks

C's isolated project was `team11-c-e7f73d1-keyword-r4`, with a fresh named PostgreSQL volume of the same prefix and migration `20261119_0007`. Source binds were read-only. API and Worker used `TEXT_PARSING_ENABLED=false`, `DOCX_PARSING_ENABLED=false`, `EMBEDDING_ENABLED=false` and `EMBEDDING_AUTO_PREPARE=false`; API setup reported `disabled` before and after recreation. C used real Microsoft Edge `158.0.4370.45` in API mode (29 traced requests, no HTTP interception, mock data or page errors). Requested and effective search mode was `keyword`, not degraded.

Root `cbc4e940-5a7c-411e-b5b8-e5fdab14f90b`, import Job `1`: **19 files, 12 `basic_ready`, 7 expected `unsupported`**. The seven rejections included corrupt, encrypted and textless PDFs, plus four non-PDF probes refused with optional parsing disabled. All seven had zero chunks. Refusing a disabled format is not an acceptance test for that format.

| Query / source file | Physical page / chunk ordinal | SHA-256 of the original PDF |
| --- | --- | --- |
| `Marker01P1` · `regression/group-a/doc01.pdf` | `1` / `1` | `cf136f2dca47a4f8d3dc00bf4061f4ef746287ee7a92e8eea4bc391ba8e48483` |
| `Marker02P2` · `regression/group-a/doc02.pdf` | `2` / `2` | `09e6b2ce75c2bab407ae4011efa3ca85b40e2aa889cfc52020a81502daed5402` |

- C's file / version / chunk for `Marker01P1`: `c678803e-726c-41f4-b39e-89a83a5bd1cf` / `df6b0f47-3ccb-4be4-bf42-f1391784a8a5` / `fe77a919-c710-4631-8c56-2a5335b474cc`.
- C's file / version / chunk for `Marker02P2`: `79a24afb-9360-495b-9441-2ad739a5d433` / `af3fad71-69b1-4a41-8c61-8ff3cbbab714` / `d8beed94-c3b0-4987-acee-b2aa859aebfe`.

For each click, the search hit and the evidence response agreed on file, version, chunk, ordinal, page and indexed text. Both passages also occur on the separately checked physical source pages (whitespace normalized); page 2's full physical text contains more than the stored chunk. Edge's separate original-file check is not an in-app native preview; the in-app preview control was disabled for this adapter.

## Rescan, recreation, and comparison with D

Job `33` was the only row added by rescan: a completed `scan_root`, with no new extraction or embedding jobs. The initial, rescanned and post-recreation snapshots matched exactly for 19 files, 19 versions, 30 chunks, 30 keyword indexes, 12 PDF metadata rows and zero token indexes. Job counts were `32 → 33 → 33`. C recorded new DB/API/Worker container IDs with the same images and the same named volume, `team11-c-e7f73d1-keyword-r4_postgres_data`. Both prior file/version/chunk tuples and their evidence were read successfully again, without another scan. Both archived Worker logs are zero-byte, so the conclusions rely on the runtime records, database snapshots and browser/API trace, not Worker log lines. One before/after evidence screenshot pair is byte-identical; the browser trace and container/snapshot records establish the readback sequence.

D compared C's archive to the separate exact-e7 PDF-off Chrome run. Both markers agreed on relative path, physical page, ordinal, exact indexed passage and original SHA-256. Independent DBs assigned different IDs as expected; C and D did not use identical application image IDs. All 15 PDF fixture hashes and all seven rejection reasons agreed. The two disabled TXT/Markdown probe files had different raw hashes, reproduced by CRLF in C's checkout vs. LF in D's; neither was indexed. This is a same-commit comparison of the PDF fallback configuration, not a bit-identical whole-stack or whole-corpus comparison.

**Joint C/D scope supported by this evidence:** text-layer PDF keyword fallback, with optional parsers and local AI off. **C NOT RUN:** PDF Hybrid, TXT, Markdown and DOCX parsing/search. C did not qualify Semantic-only, OCR, visual models, or audio/video. Any separate D-only results do not expand this C sign-off. This note does not certify the release owner's freeze, tag, or submission.

## Archive audit pointers

- Attribution, scope and checkout: `C-validation.md`, `evidence/SHA256SUMS`, `evidence/api/provenance.txt`, `evidence/api/runtime-provenance.json`.
- Browser/API and fixtures: `evidence/api/actual.json`, `evidence/api/marker01p1-search.json`, `evidence/api/marker01p1-evidence.json`, `evidence/api/marker02p2-search.json`, `evidence/api/marker02p2-evidence.json`, `evidence/api/negative-files.json`.
- Persistence: `evidence/api/scan-job.json`, `evidence/api/rescan-job.json`, `evidence/api/restart-readback.json`.
- Captures: `evidence/screenshots/01-scan-complete.png`, `03-source-01-evidence.png`, `03-source-02-evidence.png`, `03-source-01-physical-page-1.png`, `03-source-02-physical-page-2.png`, `04-rescan.png`, `05-recreated-01-evidence.png`, `05-recreated-02-evidence.png` (all under `evidence/screenshots/`).
