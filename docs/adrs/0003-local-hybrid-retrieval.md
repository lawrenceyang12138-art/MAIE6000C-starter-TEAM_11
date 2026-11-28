# ADR 0003 — Local hybrid retrieval with a keyword fallback

## Status

Implemented. This records the October 30 model replacement and the keyword
fallback retained in W13. It is not release sign-off.

## Context

The application needs exact-term lookup and retrieval by description. The
[W4 proposal](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/w04-proposal/submissions/week04/README.md)
sets a local-first boundary: after preparation, inference works offline and the
AI service receives text fragments rather than access to source files. Model
unavailability must not block keyword search or current-version evidence.

## Decision

Keep PostgreSQL keyword indexing independent of model readiness. Provide semantic
and hybrid modes through local `perplexity-ai/pplx-embed-v2-late-0.6b` at revision
`7bba8e7cf2075dec747fa8557f41eb90e70361ed`. PPLX retains 128-dimensional token
vectors and uses exact MaxSim; hybrid combines lexical and semantic scores. Keep
token matrices as derived data linked to the canonical source chunk. When semantic
retrieval cannot run, report the effective keyword mode and reason. Do not fall
back to hosted inference or reuse incompatible E5 vectors.

## Alternatives considered

- **Local dense E5**, the earlier implementation. PPLX replaced the pooled
  vector with token-level scoring. In the [dated PDF comparison](../search-team-pdf-evaluation.md#actual-pplx-validation-on-2026-10-30),
  both scored **3/5 semantic Top-3** on the small source-location set. PPLX found
  one answer E5 missed and missed one E5 found; it did not improve the total.
- **Keyword only**, the measured baseline and supported fallback. It needs no
  model and handles exact markers. On the [dated 12-query topical set](../search-validation.md#topical-retrieval-and-limits),
  verified passage Top-3 was **2/12 keyword**, **11/12 semantic** and **11/12 hybrid**.
  These synthetic measurements do not establish general search quality.

## Consequences

- Semantic retrieval needs verified local weights, warmup and compatible
  per-chunk indexes. Vectors can be regenerated without replacing source
  evidence; keyword search remains usable while the model is unavailable or
  compatible indexes are being built.
- Exact token scoring reads a matrix per chunk and increases CPU and storage
  demands relative to keyword-only retrieval. This path does not use ANN or
  establish a large-corpus performance target. See the [search guide](../search-plan.md)
  and [startup guide](../model-startup.md) for details.
