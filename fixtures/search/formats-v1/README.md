# Mixed-format source fixtures v1

`sources.zip` contains the 12 original files; `manifest.json` contains independent source hashes,
queries, exact quotes, physical PDF pages and expected bad-file outcomes. `manifest.sha256` pins
the answers. Chinese query strings are JSON Unicode escapes; the actual documents contain Chinese.

Use `python -m scripts.c_format_fixtures stage` to check and unpack the originals in the dedicated
scratch mount. Never import this directory itself. See the [runbook](../../../docs/format-validation/README.md)
and [release table](../../../docs/format-validation/role-c-handoff.md). Fixture checks are not release results.
