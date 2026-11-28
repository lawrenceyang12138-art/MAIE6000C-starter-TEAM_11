# W13 release owner handoff · Team 11

**Ready for release-owner review:** the [W13 team README](README.md), [technical brief](final-technical-brief.md), [AI Use Statement](ai-use-statement.md), [demo runbook](demo-runbook.md), [offline PDF cue card](../../output/pdf/team11-w13-pdf-demo.pdf) and [evidence and sign-off ledger](evidence/README.md). See the ledger for exact tested snapshots. The team-approved release SHA, named release owner and Canvas receipt are separate decisions, not supplied by this document.

## Course requirement vs. team schedule

- Canvas assignment **Final Team Project**: user-supplied screenshot shows **Saturday by 5:30pm**, **100 points**, **Start Assignment** and **a text entry box**. With the 2026-11-27 capture context, the due time is **Saturday, November 28, 17:30** on the assignment display; the team uses Singapore/Hong Kong time (UTC+8) and the screenshot does not display a timezone label. The separate availability shown is Nov 14 17:30 through Dec 5 17:30, subject to the course's [general late policy](https://canvas.ust.hk/courses/74201/pages/late-assignment-submission-policy). That window is **not** an extension of the due time.
- Path: [Canvas course Assignments](https://canvas.ust.hk/courses/74201/assignments) → **Final Team Project** → **Start Assignment** → **text entry box**. The course list requires login. The screenshot/HTML do not show an assignment permalink or actual Canvas group setting. An enrolled owner should confirm both and verify the due timezone at read-back. One official group submission suffices only if configured as a group assignment and not overridden by the instructor.
- Required: a pushed `w13-final` checkpoint and the root README, `docs/architecture.md`, `docs/operations.md`, `docs/adrs/`, and `submissions/week13/README.md` at that tag. Material generative AI assistance makes the AI Use Statement applicable. The complete-system contract includes persistent relational data, API, worker/async processing, integrated AI, reproducible local startup, tests/credible verification, documentation, structured logs, health checks and basic observability.
- The course recommends a `.pptx` for showing the workflow; the visible Canvas mode is text entry, not a PDF/PPTX upload. The technical brief, offline PDF cue card, runbook and evidence are repository deliverables for this team, not separate uploads.

| November 28, SGT | Decision / action | Current record |
| --- | --- | --- |
| **10:30** | Publish per-format decisions based on C and D evidence for the same candidate. If the checks are incomplete, announce them as pending and prioritize the PDF fallback. | No cleared-format announcement evidenced at this checkpoint; PR #18 merged at 11:19 |
| **13:30** | Freeze exact code/materials/evidence, resolved SHA, allowed config and demo/rollback path. Rerun affected gates on any replacement candidate; sign off against the actual frozen SHA. | Pending, no frozen candidate |
| **15:30** | Team target: finish authorized submission and independently read back. | Pending |
| **17:30** | Course due / team hard line. | Deadline, not yet submitted |

## Inputs required to freeze

1. A's [handoff](../../docs/w13-final-candidate.md) identifies tested runtime `f1091de44ffdc125a133ba78133c411f9137ebac`. [PR #18](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/pull/18) merged the same runtime into `develop` at `7a9fa8087d304f7c126fdc290dc21a98334b7972` (only A's two handoff Markdown files differ). The D source-inspector patch and submission artifacts go on top. Keep A's measured scope distinct from the new packaged candidate.
2. B supplies actual parser boundaries and human gold/AI-use status. C supplies named per-format pass/fail/skip records and the AI-step result on the same candidate and config. D tests in a real browser as in the [runbook](demo-runbook.md). Record C/D independently in the [ledger](evidence/README.md). `TEXT_PARSING_ENABLED` gates TXT and MD **together**; `DOCX_PARSING_ENABLED` gates DOCX separately. Both default off. If only one of TXT/MD clears the gate, leave the shared switch off unless A supplies an independently gated configuration and the changed path is reverified.
3. The named release owner checks support and limits, actual demo or labelled same-candidate recording, required paths and explicit team acceptance. For the full tagged SHA, use the resolved tag externally; the tagged commit cannot contain its own hash.

## Integrate on develop, then promote to main

The team integrates on `develop` first. At the ref check, `origin/main` was an ancestor of `origin/develop` with no main-only commits. Both branches are protected; run a normal reviewed promotion rather than force-updating branch history.

1. Review the local D changes and integrate by approved PR into `develop`. Check the actual merge result and freeze its runtime, artifact links and acceptance evidence. Invalidate or rerun affected tests if the runtime/configuration/fixtures change.
2. If authorized, promote the approved integration to `main` via the normal `develop` → `main` PR. Compare the promoted tree against the accepted one. If promotion produces a different SHA, record it and recheck the actual target before tagging. The course requires a reachable `w13-final`, not a branch named `main`; don't tag an untested tip simply to match the branch.
3. Only with explicit approval perform any push, tag or course submission. Resolve the remote tag to its **commit** (the peeled `^{}` ref for an annotated tag), verify the full SHA and open the required repo documents at that tag. Save the verified demo and limitation summary for the release owner. No external write or course submission is claimed here.

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
