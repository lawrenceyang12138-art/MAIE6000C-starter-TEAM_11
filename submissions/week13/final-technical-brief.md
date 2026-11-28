# Final Technical Brief and Postmortem

**File Management Assistant · MAIE 6000C Team 11**

Updated 2026-11-28 (SGT). This brief describes the implementation and available evidence, not a W13 release approval. Release-dependent claims are tracked in the [evidence index](evidence/README.md) and [release handoff](release-handoff.md).

## 1. Executive summary

The project helps users recover specific evidence from local folders without giving the application write access to their source documents. A user authorizes a directory, tracks asynchronous processing, and searches for a passage tied to the current version of an original. The release priority is a reproducible text-PDF workflow with visible failures. Plain-text and Word formats are independent release decisions and do not block the PDF fallback.

## 2. Final architecture

```text
Browser / nginx -> FastAPI -> PostgreSQL (roots, jobs, files, versions, chunks)
                               ^        |
                               |        v
                 indexes and status <- Worker <- read-only source mount
                                          |
                                    local embedding service (when enabled)
```

The API and Worker share the allowlisted read-only source mount. Authorizing a root commits the root and a `scan_root` job together. The Worker hashes the original bytes, reuses unchanged content versions, and runs extraction and indexing asynchronously. It publishes chunks and keyword readiness together. Durable jobs have leases and guarded writes; an abandoned attempt can be reclaimed without allowing a stale owner to publish over the new owner ([lease ADR](../../docs/adrs/0002-queue-leases.md)).

The UI uses `POST /search`, then `GET /evidence/{chunk_id}` to open the exact passage. The latter checks containment, authorization, presence, current version and source SHA-256/size. The locator is a PDF physical page or the immutable chunk's ordinal if there is no page. The UI is not a source of page or version identities. PDF rule-based relation candidates and saved review revisions remain in the existing product; they are not required for this demonstration. The Worker groups TXT/Markdown behind `TEXT_PARSING_ENABLED` and enables DOCX via `DOCX_PARSING_ENABLED`. Both default off, and neither retroactively reprocesses old unsupported versions. Separate release decisions for TXT and Markdown do not imply separate switches.

## 3. AI component in context

The integrated AI function is local semantic retrieval using the pinned `pplx-embed-v2-late-0.6b` revision `7bba8e7cf2075dec747fa8557f41eb90e70361ed`. The Worker indexes 128-dimensional token vectors, and query inference with exact MaxSim scores source chunks. Hybrid combines lexical/semantic scores using 0.65/0.35 weights. Search returns evidence passages, not synthesized answers. The model service receives text for embedding, not source filesystem access. There is no hosted inference fallback.

The API can be ready before the model. `basic_ready` is enough for keyword search; model readiness and compatible document vectors are both needed for effective semantic search. Requested/effective mode and degradation are distinct. A keyword-only run demonstrates availability under AI loss, not the integrated AI step of the course demo. The [AI startup guide](../../docs/model-startup.md) and [demo runbook](demo-runbook.md#demonstrate-the-integrated-ai-step) cover the separate verification.

## 4. Evidence-based evaluation

| Dimension | What the evidence covers |
| --- | --- |
| Functionality | A's Worker/API verification used `f1091de`. On D's local `b3bbb2e` candidate, browser tests checked two original PDF pages, 15 PDF file states both with parsers off and on, and 10/10 same-version keyword cases on C's 12-fixture mixed corpus. TXT, Markdown and DOCX opened six unpaged English/Chinese passages and each had a distinct visible rejection. These are D results, not C's sign-off or broad corpus coverage. |
| Reliability | On `b3bbb2e`, the two projects' browser rescans added only `scan_root` jobs; versions, chunks and indexes were stable. After PDF DB/API/Worker recreation, the same named volume preserved the rows and both browser evidence reads. The mixed and AI projects were not tested for same-volume recreation. A and C's earlier runs remain separate. |
| Integrated AI | On a separate model-ready `b3bbb2e` stack, the PDF `Marker01P1` Hybrid control was effective and not degraded; it reopened the original page with a positive semantic score and compatible 128-dimensional vectors. The run did not test Semantic-only or non-PDF AI retrieval. |
| Retrieval quality | In C's 12 topical queries (no navigation), verified passage Top-3 was keyword **2/12**, semantic **11/12**, hybrid **11/12**. Separate exact marker controls were **5/5** keyword Top-1. The missed `T01` had the right file and the wrong page. The English synthetic documents, six paired topics, and unapproved labels/threshold do not establish deployment-wide quality. |
| Performance | On the same dated single-client, CPU/loopback run (28 files, 54 chunks, 24 timed queries per mode), p95 was **10.54 ms keyword / 215.61 ms semantic / 187.97 ms hybrid**. This excluded startup and evidence reads; it is not a release target, larger-scale or concurrent-client result. |
| Reproducibility | The launcher/Compose configuration, pinned model revision, Alembic migrations and frozen fixtures provide repeatable inputs. Rebuild against the actual candidate, rather than use images from another SHA or a checkout with converted fixture bytes. |
| Operations and data boundary | `/health/live`, `/health/ready`, `/setup`, `/metrics`, and structured API/Worker logs expose database, model and processing state. Local loopback ports, allowlisted read-only mounts and current-source checks limit scope. This is not a multi-user security or privacy certification. |

Sources: [D's current browser and durability record](evidence/d-browser-20261128.md), [A's PDF baseline](../../docs/w13-pdf-baseline.md), [A's candidate verification](../../docs/w13-final-candidate.md), [C's dated search validation](../../docs/search-validation.md#2026-11-23-validation-results) and [C's machine-readable summary](sections/C-validation.json). A's latest handoff establishes `develop` merge `7a9fa8087d304f7c126fdc290dc21a98334b7972` as the integration baseline, differing from A's tested code only in two handoff files. The separate D evidence covers the local `b3bbb2e` candidate with the locator adjustment. No format is currently jointly cleared by C and D; verify the exact assembled release using the [demo runbook](demo-runbook.md).

## 5. Engineering trade-offs

- Keyword indexing is independent of the model to keep source retrieval available on a cold or offline machine, at the cost of weaker topical retrieval on the synthetic benchmark.
- Revalidating file version and hash before showing a passage costs local I/O but prevents an older or unauthorized chunk being presented as the current original.
- Exact token scoring keeps this implementation simple and measurable on a small corpus; larger collections need separate scale testing. PDF pages are meaningful; text chunks carry a stable ordinal, not fabricated pagination.
- The PDF fallback and a short core flow take precedence over unverified format expansion. An accepted new format needs positive, negative, and shared regression coverage, not merely an extraction success.

## 6. Postmortem

The initial [W4 scope](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/w04-proposal/submissions/week04/README.md#scope-and-primary-workflow) was broader than this release: automatic monitoring, other formats, OCR, expanded graph coverage, export and revocation were R1 goals, not W13 achievements. This release also does not include visual-model integration, audio/video, or file operations.

The search UI's original page-count guard assumed every matched source was paginated. The W13 adjustment removes that dependency for canonical search-hit evidence; nullable page metadata is no longer treated as a reason to fabricate a page or block a valid passage. This frontend change does not add a parser. A Windows checkout also exposed a fixture-byte problem: several working-copy files were CRLF-converted before the binary attributes changed. Use exact frozen bytes in a separate checkout and compare hashes; do not rewrite the manifest or declare parser failure from altered fixtures.

## 7. Next steps

Obtain C's exact-SHA/configuration verification and the team's release approval, then read back the tagged README and demo on the actual frozen release. Expand the format matrix beyond the observed multilingual keyword and rejection controls only after that: higher chunk ordinals, byte and container limits, non-PDF model retrieval, and reviewed source labels on new collections. Reprocessing old unsupported versions remains future work. OCR and other media are outside this release.
