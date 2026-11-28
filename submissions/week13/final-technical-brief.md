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
| Functionality | In A's 2026-11-28 run on `f1091de44ffdc125a133ba78133c411f9137ebac`, the `regression` subset had 12 readable PDFs and one unsupported file with both extra-format switches off. The `maintenance` keyword probe resolved to `doc03.pdf` physical page 1 both off and on. With both switches on, one TXT, one Markdown and one DOCX probe returned the matching passage and a null page number. These are Worker/API checks, not multilingual, negative-input or browser sign-off for those formats. |
| Reliability | A's 2026-11-27 baseline `16251df8b1167a740d7f29863144a3859a65e4b9` recorded rejection reasons for abnormal PDFs, stable rescan counts and evidence persistence after restart. A separately verified rescan and restart on `f1091de`. C's dated runtime `5eb12cff3f0eaac0b5b0f4ca1b75524e052de06f` passed 202/202 W7 HTTP/DB checks with AI off and recovered 54/54 compatible token matrices on its separate 28-file root. Revalidation on the assembled revision is pending. |
| Retrieval quality | In C's 12 topical queries (no navigation), verified passage Top-3 was keyword **2/12**, semantic **11/12**, hybrid **11/12**. Separate exact marker controls were **5/5** keyword Top-1. The missed `T01` had the right file and the wrong page. The English synthetic documents, six paired topics, and unapproved labels/threshold do not establish deployment-wide quality. |
| Performance | On the same dated single-client, CPU/loopback run (28 files, 54 chunks, 24 timed queries per mode), p95 was **10.54 ms keyword / 215.61 ms semantic / 187.97 ms hybrid**. This excluded startup and evidence reads; it is not a release target, larger-scale or concurrent-client result. |
| Reproducibility | The launcher/Compose configuration, pinned model revision, Alembic migrations and frozen fixtures provide repeatable inputs. Rebuild against the actual candidate, rather than use images from another SHA or a checkout with converted fixture bytes. |
| Operations and data boundary | `/health/live`, `/health/ready`, `/setup`, `/metrics`, and structured API/Worker logs expose database, model and processing state. Local loopback ports, allowlisted read-only mounts and current-source checks limit scope. This is not a multi-user security or privacy certification. |

Sources: [A's PDF baseline](../../docs/w13-pdf-baseline.md), [A's candidate verification](../../docs/w13-final-candidate.md), [C's dated search validation](../../docs/search-validation.md#2026-11-23-validation-results) and [C's machine-readable summary](sections/C-validation.json). The `develop` merge `7a9fa8087d304f7c126fdc290dc21a98334b7972` differs from A's tested code by the two A handoff documents only. The local D frontend patch is not in either revision. Use the [demo runbook](demo-runbook.md) to repeat the browser checks on the assembled revision and record actual outcomes in the [evidence index](evidence/README.md); no format is currently signed off by C and D.

## 5. Engineering trade-offs

- Keyword indexing is independent of the model to keep source retrieval available on a cold or offline machine, at the cost of weaker topical retrieval on the synthetic benchmark.
- Revalidating file version and hash before showing a passage costs local I/O but prevents an older or unauthorized chunk being presented as the current original.
- Exact token scoring keeps this implementation simple and measurable on a small corpus; larger collections need separate scale testing. PDF pages are meaningful; text chunks carry a stable ordinal, not fabricated pagination.
- The PDF fallback and a short core flow take precedence over unverified format expansion. An accepted new format needs positive, negative, and shared regression coverage, not merely an extraction success.

## 6. Postmortem

The initial [W4 scope](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/w04-proposal/submissions/week04/README.md#scope-and-primary-workflow) was broader than this release: automatic monitoring, other formats, OCR, expanded graph coverage, export and revocation were R1 goals, not W13 achievements. This release also does not include visual-model integration, audio/video, or file operations.

The search UI's original page-count guard assumed every matched source was paginated. The W13 adjustment removes that dependency for canonical search-hit evidence; nullable page metadata is no longer treated as a reason to fabricate a page or block a valid passage. This frontend change does not add a parser. A Windows checkout also exposed a fixture-byte problem: several working-copy files were CRLF-converted before the binary attributes changed. Use exact frozen bytes in a separate checkout and compare hashes; do not rewrite the manifest or declare parser failure from altered fixtures.

## 7. Next steps

First complete the PDF and local AI demonstration on the frozen candidate and obtain actual sign-off. Then verify text formats independently with multilingual and rejected inputs, address old-format reprocessing, and broaden the evaluation with reviewed source labels and new collections. OCR and other media need their own safety, provenance and resource limits; they are outside this release.
