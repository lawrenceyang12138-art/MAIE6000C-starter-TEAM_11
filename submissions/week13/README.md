# Week 13 Final Team Project · File Management Assistant

**MAIE 6000C Team 11** · [Team repository](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11) · Required tag: `w13-final`

**Release status (2026-11-28 SGT):** A's handoff confirms `develop` merge `7a9fa8087d304f7c126fdc290dc21a98334b7972` as the integration baseline. [Role C](evidence/c-independent-pdf-20261128.md) and [Role D](evidence/d-browser-20261128.md) independently passed the PDF keyword fallback on local review commit `e7f73d14e112031131d0383d4698d6767fea0c8c`. This is technical acceptance of that commit and configuration. The final promoted SHA, human release approval, remote tag and Canvas receipt are not recorded here.

## 1. Workflow and support

File Management Assistant helps users find passages in a selected local folder. The user grants read-only access to an allowlisted mount; the API creates a scan job; the Worker hashes, versions, parses and indexes readable files; and keyword search can run without the model. Opening a search hit uses the existing source inspector and the canonical chunk evidence endpoint. The service revalidates the current, authorized source bytes before returning the passage. PDF uses the actual physical page; a pageless chunk uses its persisted ordinal (`原文片段 #N`). This is passage retrieval, not a new document preview or a generated answer.

**Jointly verified demo scope on `e7f73d1`: PDF with a readable text layer, keyword mode, both optional parsers and AI off.** TXT, Markdown and DOCX remain out of the supported set; C explicitly did not run them. Keep `TEXT_PARSING_ENABLED` (TXT and literal Markdown) and `DOCX_PARSING_ENABLED` off. D's separate PDF Hybrid example is live AI evidence, not joint C/D approval of Hybrid. See the [format and sign-off matrix](evidence/README.md#current-format-gates).

## 2. Demo order

1. Open the API-mode browser, select the configured read-only corpus and authorize it. Capture the real accepted root and scan Job ID.
2. Follow the Worker progress to persisted file states. Show the reason for one rejected PDF while valid neighbors finish.
3. Search `Marker01P1` by keyword and open the evidence for `regression/group-a/doc01.pdf`, physical page 1. Check `Marker02P2` on page 2 of `doc02.pdf` as a second locator control.
4. For the integrated AI step, show D's separate local **Hybrid** example only after the live model reports ready: effective Hybrid with no degradation and the verified original passage. C did not run this step. The keyword fallback alone is not evidence of working AI.
5. Rescan, then re-read the original evidence after recreating services with the same database volume. Show unchanged identities and source hashes, with no duplicate extraction or indexing jobs.
6. Show API/database readiness, Worker logs and metrics. Explain the text-layer limitation and reproduce the main path using the [demo runbook](demo-runbook.md).

## 3. Components and ownership

| Role | Component and responsibility |
| --- | --- |
| A | FastAPI authorization and scan dispatch, durable jobs, PostgreSQL persistence and release-candidate assembly |
| B | Document extraction, evidence and rule-based relation/review pipeline |
| C | Keyword and local PPLX semantic/hybrid search, model readiness, retrieval verification |
| D | Browser workflow and source inspector, end-to-end acceptance and milestone packaging |

The UI is served by nginx/Vite. Compose joins the API, Worker, PostgreSQL/pgvector and optional local model service. Alembic manages the shared schema; the source mount is read-only in both the API and the Worker.

## 4. Verification and limitations

The [evidence index](evidence/README.md) separates the two same-commit browser runs from A's earlier [PDF baseline](../../docs/w13-pdf-baseline.md), [Worker/API results](../../docs/w13-final-candidate.md) and [C's dated search experiments](../../docs/search-validation.md#2026-11-23-validation-results). Both PDF runs opened the canonical text at physical pages 1 and 2 in the inspector and survived separate same-volume container recreations. The source pages were checked independently; this does not claim a new in-app PDF viewer. D's mixed run covered six pageless keyword hits with genuine ordinals, not non-PDF semantic/hybrid. The offline PDF cue card illustrates real fixture locations; it is not a live recording. Historical gold and quality/performance results do not substitute for release sign-off.

No OCR, visual model, audio or video is delivered. Do not claim automatic directory monitoring, broad graph coverage, export/purge, an authorization-revocation workflow or file moves, renames and undo. Old unsupported files are not automatically reprocessed by enabling a new format. Do not claim Markdown rendering, Word pagination, or rich Word layout.

## 5. Reproduce and review

- [Run and operate the system](../../README.md) · [Operations](../../docs/operations.md) · [Architecture](../../docs/architecture.md) · [ADRs](../../docs/adrs/)
- [Technical brief and postmortem](final-technical-brief.md) · [Demo and capture steps](demo-runbook.md) · [Offline PDF cue card](../../output/pdf/team11-w13-pdf-demo.pdf) · [Evidence and sign-offs](evidence/README.md)
- [Release and Canvas handoff](release-handoff.md)
- [AI Use Statement](ai-use-statement.md): Codex materially assisted this package and the frontend work; the statement separates recorded checks from human approval.
