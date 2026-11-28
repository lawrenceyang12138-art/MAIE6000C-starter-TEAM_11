# Final candidate — integration/w13-final

Prepared 2026-11-28 by A. This is the SHA to verify and to submit; `develop` is
the base and was not modified by A.

## SHA

```
branch       integration/w13-final
code commit  f1091de44ffdc125a133ba78133c411f9137ebac
base         develop 61c272b (Merge PR #17)
```

The branch head carries one more commit that adds this document only; the code
under test, and the SHA every result below refers to, is `f1091de`. Check with
`git diff --stat f1091de..HEAD` - it lists this file and nothing else.

Three commits sit on top of `develop`:

```
f1091de feat(config): expose per-format switches and mount the probe fixtures
f0b4570 fix(fixtures): mark the remaining frozen fixtures as binary text
19e24e8 fix(fixtures): keep PDF and search fixtures byte-exact on checkout
61c272b (develop)
```

Why a branch instead of `develop`: the two `.gitattributes` fixes and the
compose/.env switches are A's integration work and are **not** in `develop`.
The submission should use this branch, or `develop` must receive those three
commits first. Everything else in the branch is exactly `develop`.

## Important history note

PR #13 was merged and then reverted and re-landed through PR #15
(`9bbf697` → `b4dbecc` → `3818aa9` → `7c09302` → `bfe6aec`). The parsing code
now in `develop` is the re-landed implementation, **not** the code PR #13 ended
with. Every result below was produced on that re-landed code, not on `623cbfc`.

## Configuration

Worker only, both default off:

| Variable | Enables | Default |
| --- | --- | --- |
| `TEXT_PARSING_ENABLED` | `.txt`, `.md` (strict UTF-8) | `false` |
| `DOCX_PARSING_ENABLED` | `.docx` (OOXML body text) | `false` |
| `TEXT_MAX_BYTES` | per-document byte cap, hard-capped at 2 MiB | 2097152 |

Start:

```bash
# formats off (baseline path)
API_HOST_PORT=8581 FRONTEND_HOST_PORT=3150 POSTGRES_HOST_PORT=15440 \
  docker compose -p team11-final up -d

# formats on
API_HOST_PORT=8581 FRONTEND_HOST_PORT=3150 POSTGRES_HOST_PORT=15440 \
TEXT_PARSING_ENABLED=true DOCX_PARSING_ENABLED=true \
  docker compose -p team11-final up -d --force-recreate worker
```

Ports are examples chosen because this host's Windows reserved ranges moved;
any free ports work.

## Verification

Static and test results:

```
ruff check .                                     clean
alembic heads                                    20261119_0007 (single head)
pytest (develop 61c272b, unit + integration)      899 passed, 21 skipped
pytest (candidate, parsing/worker/frozen suites)  104 passed
```

Live matrix, fresh database per row, candidate `f1091de`:

| Switches | Root | Files | Result |
| --- | --- | --- | --- |
| off | `regression` | 13 | 12 `basic_ready` + 1 `unsupported` — identical to the `16251df` baseline |
| on | `regression` | 13 | 13 readable; every PDF result unchanged |
| on | `formats` | 3 | TXT / MD / DOCX `basic_ready`; each probe term resolves to its own file and passage |
| TXT only | `formats` | 3 | TXT + MD ready, DOCX `unsupported_format` |
| DOCX only | `formats` | 3 | DOCX ready, TXT + MD `unsupported_format` |

Search/evidence spot checks: `maintenance` → `doc03.pdf` page 1 in both off and
on runs; `text-probe-4187`, `markdown-probe-7143`, `docx-probe-2251` each return
the matching file with the marker in the evidence text. Text/DOCX hits carry
`page_number = null`.

## What is verified and what is not

Verified here: parsing, keyword indexing, keyword search, evidence, rescan
idempotency, restart persistence, PDF non-regression, per-format switching.

Not verified here: semantic and hybrid retrieval for non-PDF chunks (C's check),
and the UI rendering of null pages (D's check).

## Known behaviours that are not defects

- Text and DOCX have no pages; `page_number` is `null` by design.
- Relation candidates are PDF-only; TXT/MD/DOCX publish chunks and keyword
  indexes without entity candidates.
- Keyword search is OR-based: a query can return a weak hit from another file
  that shares a term. Judge a disabled format by `unsupported_format`, not by
  "zero results".
- Switch changes apply to new extractions; already-terminal versions are not
  reclassified.

## Rollback

- Formats on → off: set both switches to `false`, recreate the worker. No data
  rewrite, no migration.
- Whole candidate → baseline: `git checkout 61c272b`. The branch is disposable.
- No database migration is added by this branch; do not run `alembic upgrade`
  against a team database for it.

## For C and D

- C: use `f1091de`, run your 12-file corpus with both switches on; record the
  SHA in your results. Null-page and keyword expectations as above.
- D: browser check on the same SHA, with formats on and off; confirm PDF page
  navigation is unchanged and non-PDF results do not offer page jumps.
