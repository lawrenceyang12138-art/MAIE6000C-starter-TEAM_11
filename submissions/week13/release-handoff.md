# W13 release owner handoff · Team 11

**Ready for release-owner review:** the [W13 team README](README.md), [technical brief](final-technical-brief.md), [AI Use Statement](ai-use-statement.md), [demo runbook](demo-runbook.md), [offline PDF cue card](../../output/pdf/team11-w13-pdf-demo.pdf), [evidence ledger](evidence/README.md) and [ADRs](../../docs/adrs/). The technical review point is `e7f73d14e112031131d0383d4698d6767fea0c8c`, not the final release SHA. The C/D tests are attributed to that exact checkout. This materials follow-up is documentation only; the final merge and tag still need their own tree/read-back and team approval.

**Freeze recommendation:** only the C/D-verified text-layer PDF keyword fallback. Keep TXT/Markdown, DOCX and embeddings off for that run. C's independent Edge report (Role C/Codex, 13:07 SGT) and D's Chrome report agree on the two real pages, expected rejections, stable rescan and same-volume read-back. C explicitly did not run Hybrid or the optional formats. D's separate non-degraded PDF Hybrid run is eligible as a distinct live AI demonstration when the model is ready, not joint Hybrid verification. The cue card is a fallback explanation, not a live recording.

**Reproduce the tested runtime without a push:** internal `team11-w13-d-package-e7f73d1.bundle` (SHA-256 `a3889cc45b4cdd8ca9c11375c02267b053222676378736eaa16d22d6ca61ffa4`) transfers e7 against A's `7a9fa80` baseline. The [C evidence digest](evidence/c-independent-pdf-20261128.md) pins C's reply separately. Neither the bundle nor an internal evidence ZIP is a Canvas upload or published tag.

## Course requirement vs. team schedule

- Canvas assignment **Final Team Project**: user-supplied screenshot shows **Saturday by 5:30pm**, **100 points**, **Start Assignment** and **a text entry box**. With the 2026-11-27 capture context, the due time is **Saturday, November 28, 17:30** on the assignment display; the team uses Singapore/Hong Kong time (UTC+8) and the screenshot does not display a timezone label. The separate availability shown is Nov 14 17:30 through Dec 5 17:30, subject to the course's [general late policy](https://canvas.ust.hk/courses/74201/pages/late-assignment-submission-policy). That window is **not** an extension of the due time.
- Path: [Canvas course Assignments](https://canvas.ust.hk/courses/74201/assignments) → **Final Team Project** → **Start Assignment** → **text entry box**. The course list requires login. The screenshot/HTML do not show an assignment permalink or actual Canvas group setting. An enrolled owner should confirm both and verify the due timezone at read-back. One official group submission suffices only if configured as a group assignment and not overridden by the instructor.
- Required: a pushed `w13-final` checkpoint and the root README, `docs/architecture.md`, `docs/operations.md`, `docs/adrs/`, and `submissions/week13/README.md` at that tag. Material generative AI assistance makes the AI Use Statement applicable. The complete-system contract includes persistent relational data, API, worker/async processing, integrated AI, reproducible local startup, tests/credible verification, documentation, structured logs, health checks and basic observability.
- The instructor's ADR clarification asks for the team's real decisions, rationale, considered alternatives and trade-offs in `docs/adrs/`. The example topics, numbering and filenames are illustrative, not additional deliverables.
- The course recommends a `.pptx` for showing the workflow; the visible Canvas mode is text entry, not a PDF/PPTX upload. The technical brief, offline PDF cue card, runbook and evidence are repository deliverables for this team, not separate uploads.

| November 28, SGT | Decision / action | Current record |
| --- | --- | --- |
| **10:30** | Publish per-format decisions based on matching C/D evidence. | No announcement evidenced by 10:30; C's PDF result was recorded at 13:07 and is not backdated. |
| **13:30** | Freeze exact code/materials/evidence, resolved SHA, allowed configuration and demo/rollback path. | PDF-keyword-only recommendation and local materials available; actual team freeze and release SHA not recorded. |
| **15:30** | Team target: finish authorized submission and independently read back. | Pending |
| **17:30** | Course due / team hard line. | Deadline, not yet submitted |

## Inputs required to freeze

1. A's [tracked runtime record](../../docs/w13-final-candidate.md) identifies tested `f1091de`, two handoff documents before the integration baseline `7a9fa80`. It does not cover D's locator patch. For technical review use e7, and for approval choose and record the actual reviewed materials and release tree.
2. The [C/D ledger](evidence/README.md#current-format-gates) now covers PDF keyword only. Do not wait for optional tests to prepare the PDF-only freeze. `TEXT_PARSING_ENABLED` gates TXT and MD **together**; `DOCX_PARSING_ENABLED` is separate. Both stay off. C's Hybrid skip does not invalidate the fallback and may not be replaced by D's result in the C column.
3. Obtain A/B's actual material AI-use or no-use confirmations; do not infer them from W7 or from the runtime model. B's human gold review is still unconfirmed, so no benchmark is represented as human-approved. Confirm the release/submission owner and explicit permission for remote actions. The owner checks the required paths, actual demo proof and release scope, then approves the exact frozen SHA. Use the resolved tag externally; a commit cannot contain its own hash.

## Integrate on develop, then promote to main

The team integrates on `develop` first. The 2026-11-28 SGT fetch and GitHub ref check found local and remote `develop` at `7a9fa8087d304f7c126fdc290dc21a98334b7972`, `main` at `abacacd0ea64c8393a1114f8acafa54dfb7c60a1`, and no remote `w13-final`. `main` was an ancestor of `develop` (0 main-only / 289 develop-only commits); GitHub reported both branches protected. Recheck these refs immediately before opening or merging PRs. Use the normal reviewed promotion.

1. Review the local D branch and integrate by approved PR into `develop`. Verify that the only changes from tested `e7f73d1` are the reviewed W13 Markdown and ADRs; executable code, configuration, fixtures and offline PDF must be unchanged for the technical evidence to apply to the same runtime. Rerun affected live gates if those inputs change.
2. If authorized, promote the reviewed `develop` tree to `main` via the normal PR. The team expects the final checkpoint on `main`, even though Canvas only requires a reachable tag. Compare the promoted tree against the approved materials tree (`git diff --exit-code <reviewed-materials-sha> <promoted-sha>`). Record the actual `main` SHA, recheck the required files and run a real-browser PDF smoke read-back before tag approval. Reapprove against the actual promoted SHA; do not relabel the original C/D reports as having run on it.
3. Only with explicit approval perform any push, tag or course submission. Resolve the remote tag to its **commit** (the peeled `^{}` ref for an annotated tag), verify the full SHA and its presence on `main`, and open the required repository documents and evidence index at that tag. Save the verified demo and limitation summary for the release owner. No external write or course submission is claimed here.

## Canvas text to fill after freeze

Copy the six fields in this order using real values. Do **not** submit the draft until the SHA and note are known. The note should name the actual verified demo path and distinguish live/recorded, AI demonstrated/unverified, and material omitted formats.

```text
Repository: https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11
  Required tag: w13-final
  Tagged commit SHA:
  Primary artifact: submissions/week13/README.md
  Team name: MAIE 6000C Team 11
  Final demo readiness note:
```

After authorized submission, an independent reviewer opens the Canvas submission, checks the visible timestamp and six lines, resolves the remote tag to the same full SHA, opens the README and its artifact/evidence links at the tag, checks the agreed demo notes, and records the receipt and reviewer. Do not report read-back complete until it occurred.
