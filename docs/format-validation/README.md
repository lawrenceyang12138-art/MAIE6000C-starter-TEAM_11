# Reproduce the Role C mixed-format gate

Use the [handoff table](role-c-handoff.md) for status; this page is the protocol, not a result.

## Prepare without deciding a release

From the repository root, use the host validation dependencies from `.[dev]`. The frozen inputs
are [sources.zip](../../fixtures/search/formats-v1/sources.zip), the [answer manifest](../../fixtures/search/formats-v1/manifest.json)
and its SHA-256. The archive carries the actual bilingual bytes, including valid Word documents and
physical PDFs. No answers, archives or manifests are inside the mounted source directory. Do not
regenerate answers after inspecting a candidate. A changed corpus gets a new suite version.

```cmd
python -m scripts.c_format_fixtures check
python -m scripts.c_format_fixtures stage
```

`check` reads the original TXT/MD bytes, WordprocessingML and PDF pages independently of the product
parser; it checks every hash, language/source location, unique keyword, quote and physical page.
`stage` writes exactly 12 files under `work/c-format-validation/sources`. It refuses unexpected or
changed files rather than removing or overwriting them. The files `01-en`, `02-bad`, `03-zh` are
neighbors in each format directory and are imported through **one** root. The absent keyword
`sundialquartznotpresent` must never match. To print the Chinese queries instead of JSON escapes:

```cmd
python -X utf8 -c "from scripts.c_format_fixtures import load; [print(p, q['keyword'], repr(q['quote']), q['page']) for p,r in load()[1].items() for q in r.get('queries',[])]"
```

## When A supplies an integrated SHA and parser flags

1. Obtain A's **40-character commit**, format scope and effective settings. Fetch that commit into
   the local Git object database first; the harness does not switch branches. Do not substitute a
   feature PR head or `develop`. Save only the parser flags to a local, untracked file. The current
   contract requires explicit `TEXT_PARSING_ENABLED` and `DOCX_PARSING_ENABLED` (`true` or `false`);
   `TEXT_MAX_BYTES` is optional. Do not feed in a product `.env`, passwords or ranking knobs. If
   A uses other switches, reconcile them before running; do not guess their meaning.
2. Have Docker running, the `pgvector/pgvector:pg16` image available, and the chosen loopback ports
   free (default: API `18086`, PostgreSQL `15486`). Substitute A's actual values for the two CMD
   environment variables below. Example scope: TXT and MD; add `docx` only if approved. PDF is always
   included; use `--formats pdf` on a fresh fallback run. Use a new run ID for every attempt.

```cmd
python -m scripts.verify_c_formats --candidate-sha %A_CANDIDATE_SHA% --flags "%A_PARSER_FLAGS%" --formats txt md --run-id rc1
```

3. The harness builds the candidate's **Git archive**, checks the running API/Worker image IDs,
   revision and flags, and uses an isolated Compose project (`team11-c-format-<run-id>`) and new
   PostgreSQL volume/database `c_format_gate`. The bind mount is read-only and contains only this
   suite. No AI service or model mount exists: embedding and auto-prepare are off, both model
   runtimes are offline and every search explicitly requests `keyword`. No seed, direct database
   insert, manual indexing, model download or ranking change is part of this protocol.
4. Raw HTTP request/response bodies, Worker jobs and SQL snapshots, current source hashes, image SHA,
   both scans and per-case decisions are recorded in `work/c-format-validation/reports/<run-id>/actual.json`.
   Its sibling `handoff.md` contains the five-column table for D. No prior report is read or
   overwritten. The stack remains available for D. Stop only the named project after D's recheck;
   do not remove other projects or volumes. A failed build or unreachable service is not a pass.

## What earns a pass

- The API authorizes one fresh root; a real Worker completes the scan. For every in-scope positive,
  `/files`, the DB current pointer and the bytes in the manifest agree. The version is `basic_ready`
  with an actual extraction attempt and a keyword index. The primary query is **root-wide**, not
  prefiltered to the expected file. It must retrieve that file; no relevance benchmark is implied.
- Read `GET /evidence/{chunk_id}` from each hit. Check root/file/path, current version, chunk ID,
  ordinal, source SHA, page and passage against the DB and the independently decoded original.
  Native evidence must keep meaningful line breaks, hyphens and indentation (the DOCX paragraph
  separator may vary); only PDF layout whitespace is folded for comparison.
- Non-PDF pages are explicitly `null`, all actual chunks are unpaged, and there is no PDF page-count
  record. A file-scoped `keyword + " page 97"` probe must still return the same unpaged passage.
  Keyword mode alone cannot prove bypass of active PDF navigation: a separate **read-only probe**
  calls the actual candidate's page selector inside the API container for physical page 3. It must
  leave all non-PDF chunks eligible without consulting the PDF metadata loader or applying a page
  target (falling back after a missing PDF lookup is not a bypass), select p3 of the EN PDF and
  exclude pp1/2 of the ZH PDF. This is not a semantic/hybrid HTTP or front-end test.
- The bad file must have a terminal `unsupported`/`failed` state with the expected reason, zero chunks
  and zero file-scoped hits; both good neighbors must still be searchable in the same import.
  Scan that exact root again through the API. Each fixture must retain its single file/version,
  content hash, current pointer and chunk IDs. A count alone cannot hide a replaced version.
- PDF must pass with the **same flags and SHA**: exact pages and quotes on both files, including p3
  after a blank page. `PASS` requires all three cases, not just a green positive example. Shared
  failures block clearance. Candidate/backend results and D's browser check remain separate.
