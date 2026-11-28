# AI Use Statement · MAIE 6000C Team 11

## Tools used and purpose

The team confirms that **each of Roles A, B, C and D** used **OpenAI Codex, GPT, DeepSeek, and `deepseek-harness`** for W13 work. The documented uses include code and contract work, test and fixture preparation, running verification, and drafting milestone documentation. Where the records do not identify the tool behind an individual task, this statement does not assign it to one.

The application's local PPLX embedding model is part of the submitted system, separate from these development tools.

## Materially affected areas and verification

- **A and B:** Integration work covers the read-only scan and durable Worker path, format switches, document extraction and versioned evidence. [A's candidate record](../../docs/w13-final-candidate.md#verification) covers parsing, keyword and evidence probes, rescan/restart and PDF non-regression on A's tested revision. It does not state which tool contributed to each task or validate D's later frontend patch.
- **C:** The [archived contribution](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/16251df8b1167a740d7f29863144a3859a65e4b9/submissions/week13/sections/C.md#remaining-human-decisions-and-limitations) records Codex assistance with search validation, fixture drafting, test execution and reporting. The [dated retrieval study](../../docs/search-validation.md#2026-11-23-validation-results), [independent PDF keyword run](evidence/c-independent-pdf-20261128.md) and [Hybrid and mixed-format supplement](evidence/c-independent-supplement-20261128.md) are distinct. The independent evidence is Role C's technical record, not a human release signature.
- **D:** Codex assisted with the search-result inspector, focused tests, fixture-byte protection, the offline cue card, ADRs and submission materials. [D's real-browser record](evidence/d-browser-20261128.md) documents which PDF, non-PDF and Hybrid checks were run. The [evidence ledger](evidence/README.md) separates browser/API/Worker results from controlled tests, earlier evidence and release approval.

The team kept actual PDF page numbers and original, version-bound passages; non-PDF results use a real chunk ordinal instead of a fabricated page. No new preview was introduced. Mock or historical runs were not counted as current acceptance, and D-only passes were not treated as joint format approval. The offline cue card is a walkthrough, not a live run or recording.

## Responsibility

The team remains responsible for verifying and explaining the submitted code and documentation and ensuring the release claims match the tagged commit. The confirmed tool list does not attest to individual review, sign-off or course submission. Record approvals separately in the release handoff.
