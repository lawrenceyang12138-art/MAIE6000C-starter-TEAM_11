# Role C to D: new-format release gate

**Preparation only, 27 November 2026 (Singapore). No format is cleared by this table.**
The project decision point supplied by the team is **28 November 2026, 10:30 SGT**;
D still needs to confirm the official deadline and the advertised delivery scope.
`16251df8b1167a740d7f29863144a3859a65e4b9` is the preparation baseline, **not** an A candidate.
B's PR, unit tests, the earlier W7/W13 reports and the isolated database preflight are not release evidence.

| Format | Positive / negative examples | Actual result | A's candidate SHA | Evidence |
| --- | --- | --- | --- | --- |
| TXT | EN: `cobaltspindle` after a literal hyphen + line break; ZH: UTF-8 BOM / CRLF note. Bad: binary / invalid UTF-8. | UNVERIFIED | Not supplied | [TXT answers](../../fixtures/search/formats-v1/manifest.json); no Worker/search trace |
| MD | EN: `amberquill` in an indented code block; ZH: a Markdown list passage. Bad: whitespace only. | UNVERIFIED | Not supplied | [MD answers](../../fixtures/search/formats-v1/manifest.json); no Worker/search trace |
| DOCX (optional) | EN: `jadesprocket` after a Word line break; ZH: a body paragraph. Bad: not an OOXML ZIP. | UNVERIFIED | Not supplied | [DOCX answers](../../fixtures/search/formats-v1/manifest.json); no Worker/search trace |
| PDF (control / fallback) | EN: `willowprism` on p1, `onyxlantern` on p3, p2 intentionally blank; ZH: distinct passages on physical pages 1 and 2. Bad: truncated PDF. | UNVERIFIED | Not supplied | [PDF answers](../../fixtures/search/formats-v1/manifest.json); no flag-on PDF regression trace |

[Preparation evidence](preparation.json): 12 independently checked and staged files, 10 positive queries,
a separate PostgreSQL database with zero public tables. No candidate API/Worker or browser was run
for this table. [Reproduction and acceptance criteria](README.md).

**After A's handoff:** attach the *new* `handoff.md` and `actual.json` from the same run to D's review;
record the actual full SHA and flags, and keep any `FAIL` or `UNVERIFIED` rows. Each format needs
both languages, the bad-file check, unchanged rescan and a passing PDF control on this configuration.
D independently repeats the search and evidence reads in a real browser on that SHA. Non-PDF results
must not show a page, a PDF preview link with `#page=`, or a page-jump control. For PDF, open the EN
p3 and ZH p2 citations and compare with the actual source. C's backend probe is not a browser pass.

Drop DOCX first, then MD. If TXT cannot be cleared, present PDF only after the **actual fallback
configuration** has passed its own PDF checks. If a switch or SHA changes, use a new run and database.
In B's proposed config TXT/MD share a switch: dropping MD from the demo is not evidence that its
parser is disabled. A/D must agree whether a scope reduction needs a distinct build or configuration.
