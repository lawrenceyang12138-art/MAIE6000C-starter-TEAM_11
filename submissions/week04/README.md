# Week 4 — Team Architecture Proposal and Project Plan

**Project / selected brief:** File Management Assistant

**Team:** MAIE 6000C Team 11

**Checkpoint:** W04 architecture proposal; documentation only, not a completed product.

## Proposal summary

People accumulate personal and project files across folders but cannot reliably retrieve them by meaning or see how their contents connect. We propose a local-first assistant that scans a selected, authorized folder, indexes its documents, and presents keyword or semantic search results and an evidence-backed file or entity graph. Search returns files and supporting passages, not generated answers. The user can inspect sources and persist corrections to AI-derived information.

The design retains the starter's API, relational database, independent worker, internal AI service, migrations, and Compose deployment. The target adds PostgreSQL full-text search and pgvector; the graph uses relational entity, relationship, and evidence records, not a separate graph database. [The architecture document](../../docs/architecture.md) is the canonical technical proposal.

## Scope and primary workflow

| Stage | Required capability |
| --- | --- |
| W7 vertical slice | Selected folder; manual text-PDF scan; asynchronous extraction/indexing; keyword and semantic search; source evidence; basic file/topic/person/project graph; persistent human corrections; visible failures and restart verification. |
| R1 core | Retain W7 and add automatic monitoring, DOCX/TXT/Markdown support, OCR, all PRD graph entity types (files, people, organizations, projects, topics, events), metadata export, and directory-authorization revocation. |
| Stretch only | File movement, renaming, and undo of file operations. PRD F9–F11 and A9–A10 are not R1 acceptance gates. |

Folder access uses operator-preauthorized, **read-only Docker bind mounts**. The browser may choose a folder within those mounted roots; it cannot browse arbitrary host paths. The API and worker read originals, while the AI service receives only versioned text fragments. Offline operation assumes dependencies and model assets have been prepared locally; there is no cloud fallback.

The primary workflow is:

1. Select a folder inside an allowlisted mounted root.
2. Validate directory access and scope.
3. Persist the authorized directory and scan job; return a job identifier and queued status before processing finishes.
4. Discover files asynchronously and create idempotent file-version processing jobs.
5. Extract text, preserve source locations, and build search indexes.
6. Perform local AI analysis for entities, relationships, and semantic retrieval.
7. Validate evidence and persist bounded results and processing status.
8. Search, inspect source passages, browse the graph, and save review decisions.

See [the full workflow](../../docs/architecture.md#primary-workflow) and [state transitions](../../docs/architecture.md#state-transitions). Revoking directory authorization is an R1 privacy control, distinct from undoing a file operation; it must not change the original files.

## Milestone plan and ownership

The work areas below describe groups of responsibilities, not named team members or individual tasks. One member may cover multiple areas, and several members may share an area. Member assignments and the final team-review time remain to be confirmed by the team.

| Milestone | Minimum outcome / evidence | Work areas involved |
| --- | --- | --- |
| W5 | Verify mount boundaries and read-only access; agree API contracts; implement the first persisted directory/job path; validate local-model and search feasibility on a small approved corpus. | Backend/Data, AI/Worker, QA/Release |
| W7 | Demonstrate the complete manual text-PDF scan → search/graph → evidence/review loop, including visible failures and preserved state after restart. | Backend/Data, AI/Worker, Frontend, QA/Release |
| W9 | Provide reproducible Docker deployment and offline preparation; extend extraction to DOCX, TXT, and Markdown. | Backend/Data, AI/Worker, QA/Release |
| W11 | Add monitoring, OCR, metadata export, recovery, observability, and measured performance. | Backend/Data, AI/Worker, Frontend, QA/Release |
| W12 | Complete R1 acceptance checks, rehearse the demo, and fix release-blocking defects. | Backend/Data, AI/Worker, Frontend, QA/Release |
| W13 | Deliver final artifacts and documentation. Evaluate stretch work only after the core passes; no stretch delivery is promised. | Backend/Data, AI/Worker, Frontend, QA/Release |

Frontend owns folder/status/search/evidence/graph/review presentation. Backend/Data owns persistence, migrations, folder authorization, and API contracts. AI/Worker owns extraction, indexing, local analysis, and asynchronous recovery. QA/Release owns acceptance evidence, deployment reproducibility, and the release checklist; interfaces are reviewed jointly.

## Acceptance evidence to collect

These are future verification targets, not tests claimed to have passed in this documentation checkpoint.

- **Product:** retrieve relevant files across subfolders; inspect passages tied to the correct file version; traverse supported graph links with evidence; keep same-name entities distinct when identity is uncertain; preserve review decisions when the same version is processed again.
- **Reliability:** repeat a scan without duplicate versions/results; recover or visibly fail interrupted jobs; show actionable failures for damaged/unsupported input; retain keyword search and source access when AI is unavailable; prove PostgreSQL data survives normal stack restart.
- **R1/privacy:** handle changed/deleted files, OCR inputs, out-of-scope paths, metadata export, and authorization revocation; verify originals remain unchanged.
- **Measurement:** record query/indexing latency, retrieval relevance, evidence validity, graph correctness, and resource use with the device, corpus, and model configuration. Establish targets from measured feasibility work; do not report invented results or thresholds.

The [acceptance and verification section](../../docs/architecture.md#acceptance-and-verification) defines the detailed scenarios. Existing SQLite-backed starter integration tests alone do not prove PostgreSQL migration or restart behavior.

## Key risks and scope cuts

| Risk | Mitigation / decision |
| --- | --- |
| Local AI quality and device limits | Validate the model and embeddings at W5; bound work and record model versions; preserve keyword/source access without cloud fallback. |
| False entity links or unsupported relationships | Require valid source evidence; distinguish semantic-similarity links from factual relationships; avoid name-only merges; allow persistent user review. |
| Folder/container access, stale versions, and interrupted work | Use allowlisted read-only mounts, canonical containment checks, content/version identities, and transactional writes. Add timeout detection and limited retries for stalled or temporarily failed jobs, with visible failure reporting. |

The **first scope cut is file organization**: move, rename, and undo remain stretch goals, and their absence cannot fail R1. If more simplification is needed, remove advanced graph presentation and non-core recommendations before reducing search, evidence, persistence, privacy, or visible-failure guarantees. R1 monitoring, OCR, format expansion, metadata export, and directory revocation remain in the core plan.

## Artifact index

| Artifact | Location |
| --- | --- |
| Project entry and starter run/test instructions | [Root README](../../README.md) |
| Problem, user, and primary workflow | [Problem and primary user](../../docs/architecture.md#problem-and-primary-user), [Primary workflow](../../docs/architecture.md#primary-workflow) |
| System diagram and service boundaries | [Architecture flow](../../docs/architecture.md#architecture-flow), [API and service boundaries](../../docs/architecture.md#api-and-service-boundaries) |
| ERD/schema and lifecycle diagrams | [Persistent entities and schema](../../docs/architecture.md#persistent-entities-and-schema), [State transitions](../../docs/architecture.md#state-transitions) |
| Worker/AI plan and starter persistence evidence | [Worker and AI processing](../../docs/architecture.md#worker-and-ai-processing), [Starter evidence and gap analysis](../../docs/architecture.md#starter-evidence-and-gap-analysis) |
| Risks, scope priorities, and verification | [Risks and scope cuts](../../docs/architecture.md#risks-and-scope-cuts), [Acceptance and verification](../../docs/architecture.md#acceptance-and-verification) |
| Existing baseline operational notes | [Starter operations](../../docs/operations.md) |

## AI Use Statement

OpenAI Codex supported brainstorming of the core workflow, discussion of architecture options, and exploration of technology choices. It also assisted with organizing and drafting the proposal. The team remains responsible for reviewing the design, validating its feasibility, and explaining the submitted work.
