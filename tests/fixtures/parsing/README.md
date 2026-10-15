# PDF parsing fixtures

All four files here are **synthetic** and contain no real or sensitive content.
They are deliberately tiny (1-3 KB) so they can live in git.

| File | What it is | Expected outcome |
| --- | --- | --- |
| `normal.pdf` | 3 pages of generated text, one distinct marker word per page | Extracted; page numbers 1, 2, 3 preserved |
| `encrypted.pdf` | 1 page, encrypted with a user password | Rejected with reason `encrypted` |
| `corrupt.pdf` | A `%PDF-1.7` header followed by random bytes | Rejected with reason `corrupt` |
| `no_text_layer.pdf` | One page containing only filled rectangles (no text objects) | Rejected with reason `no_text_layer` |

## How they were generated

`normal.pdf` and `no_text_layer.pdf` were drawn with `reportlab`; `encrypted.pdf`
was produced by encrypting a generated page with `pypdf`; `corrupt.pdf` is a
PDF header followed by random bytes.

Generating them needs `reportlab`, which is **not** a project dependency - it is
only needed to regenerate fixtures, not to run the service or the tests. If you
need to rebuild them, generate with any environment that has `reportlab` and
`pypdf`, and keep this table accurate.

## Why they are committed rather than generated in the test

Generating them at test time would add `reportlab` to the runtime dependencies
for no production benefit. Keeping the bytes in git also means the tests assert
against a fixed input, so a change in a generation library cannot quietly change
what is being tested.
