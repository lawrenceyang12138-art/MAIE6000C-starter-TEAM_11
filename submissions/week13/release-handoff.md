# W13 release owner handoff · Team 11

**Ready for release-owner review:** the [W13 team README](README.md), [technical brief](final-technical-brief.md), [AI Use Statement](ai-use-statement.md), [demo runbook](demo-runbook.md), [offline PDF cue card](../../output/pdf/team11-w13-pdf-demo.pdf) and [evidence and sign-off ledger](evidence/README.md). **D's full browser runs were on `b3bbb2e0b73d9ba45c6c19c01680bdbb7bc77702`**, with [traces, operational checks and report hashes](evidence/d-browser-20261128.md). The documentation follow-up packages those results without changing application code or fixtures. Neither revision is the team-approved final SHA. No remote integration, published tag or Canvas receipt is claimed.

**Recommendation for rehearsal:** keep TXT/Markdown and DOCX switches off. D verified the text-layer PDF fallback and a separate local PDF Hybrid example. The PDF flow also works with the model disabled; the offline cue card is available if the stack is unavailable. D's TXT, Markdown and DOCX keyword cases passed on the mixed test stack, but none of the four formats has both C and D evidence on the same configuration yet. The jointly cleared list is still empty. Do not put optional formats in the support list or use an offline card to claim live or recorded execution.

**Reproduce D's earlier browser runs without a push:** local `work/w13/team11-w13-d-b3bbb2e.bundle` (SHA-256 `1d8b53395ab2bd74a481316db8655a0dfef5813a788746a5e91ff170f45866b9`) transfers the exact one-commit runtime revision, not this later materials follow-up. For release sign-off, obtain the current review commit or its bundle, verify its full SHA in a clone with A's `7a9fa80` baseline, and report against that exact SHA and configuration. A bundle is not a published tag.

## Course requirement vs. team schedule

- Canvas assignment **Final Team Project**: user-supplied screenshot shows **Saturday by 5:30pm**, **100 points**, **Start Assignment** and **a text entry box**. With the 2026-11-27 capture context, the due time is **Saturday, November 28, 17:30** on the assignment display; the team uses Singapore/Hong Kong time (UTC+8) and the screenshot does not display a timezone label. The separate availability shown is Nov 14 17:30 through Dec 5 17:30, subject to the course's [general late policy](https://canvas.ust.hk/courses/74201/pages/late-assignment-submission-policy). That window is **not** an extension of the due time.
- Path: [Canvas course Assignments](https://canvas.ust.hk/courses/74201/assignments) → **Final Team Project** → **Start Assignment** → **text entry box**. The course list requires login. The screenshot/HTML do not show an assignment permalink or actual Canvas group setting. An enrolled owner should confirm both and verify the due timezone at read-back. One official group submission suffices only if configured as a group assignment and not overridden by the instructor.
- Required: a pushed `w13-final` checkpoint and the root README, `docs/architecture.md`, `docs/operations.md`, `docs/adrs/`, and `submissions/week13/README.md` at that tag. Material generative AI assistance makes the AI Use Statement applicable. The complete-system contract includes persistent relational data, API, worker/async processing, integrated AI, reproducible local startup, tests/credible verification, documentation, structured logs, health checks and basic observability.
- The course recommends a `.pptx` for showing the workflow; the visible Canvas mode is text entry, not a PDF/PPTX upload. The technical brief, offline PDF cue card, runbook and evidence are repository deliverables for this team, not separate uploads.

| November 28, SGT | Decision / action | Current record |
| --- | --- | --- |
| **10:30** | Publish per-format decisions based on C and D evidence for the same candidate. If the checks are incomplete, announce them as pending and prioritize the PDF fallback. | No cleared-format announcement evidenced at this checkpoint. Current D results were recorded later; C is still pending. |
| **13:30** | Freeze exact code/materials/evidence, resolved SHA, allowed config and demo/rollback path. Rerun affected gates on any replacement candidate; sign off against the actual frozen SHA. | Local D test snapshot and materials ready for review; team freeze and actual release SHA pending. |
| **15:30** | Team target: finish authorized submission and independently read back. | Pending |
| **17:30** | Course due / team hard line. | Deadline, not yet submitted |

## Inputs required to freeze

1. A's [tracked runtime record](../../docs/w13-final-candidate.md) identifies tested `f1091de44ffdc125a133ba78133c411f9137ebac`. A's 11:50 handoff replaces the stale precheck (`bec6352` / `ed17708`) with the authoritative integration baseline `7a9fa8087d304f7c126fdc290dc21a98334b7972` ([PR #18](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/pull/18)). Only the two handoff Markdown files differ between A's tested runtime and that merge. D's locator patch and packaging are on top; do not treat any of these three SHAs as the team-approved tag until release is authorized.
2. B supplies actual parser boundaries and human gold/AI-use status. C supplies named per-format pass/fail/skip records and the AI-step result on the same candidate and config. D's real Chrome evidence is already recorded for the local candidate in the [independent ledger](evidence/README.md). `TEXT_PARSING_ENABLED` gates TXT and MD **together**; `DOCX_PARSING_ENABLED` gates DOCX separately. Both default off. If only one of TXT/MD clears the gate, leave the shared switch off unless A supplies an independently gated configuration and the changed path is reverified. Non-PDF semantic/hybrid is not verified here.
3. The named release owner checks support and limits, actual demo or labelled same-candidate recording, required paths and explicit team acceptance. For the full tagged SHA, use the resolved tag externally; the tagged commit cannot contain its own hash.

For a PDF-first decision, the minimum independent C report is the reviewer and time, full candidate SHA, both optional parser flags off, PDF positive/negative and original-location controls, and effective PDF Hybrid (or an explicit skip/failure and reason). Ask A/B for any material AI tool use or an actual no-use confirmation for this submission; do not infer it from W7. A C report for optional formats must identify each format, flags, corpus, expected/observed positives and rejections, and evidence references. An omitted test or silent response is not a pass.

## Integrate on develop, then promote to main

The team integrates on `develop` first. The 2026-11-28 SGT fetch and GitHub ref check found local and remote `develop` at `7a9fa8087d304f7c126fdc290dc21a98334b7972`, `main` at `abacacd0ea64c8393a1114f8acafa54dfb7c60a1`, and no remote `w13-final`. `main` was an ancestor of `develop` (0 main-only / 289 develop-only commits); GitHub reported both branches protected. Recheck these refs immediately before opening or merging PRs. Use the normal reviewed promotion.

1. Review the local D changes and integrate by approved PR into `develop`. Check the actual merge result and freeze its runtime, artifact links and acceptance evidence. Invalidate or rerun affected tests if the runtime/configuration/fixtures change.
2. If authorized, promote the approved integration to `main` via the normal `develop` → `main` PR. The team expects the final checkpoint on `main`, even though Canvas itself only requires a reachable tag. Compare the promoted tree against the accepted one (`git diff --exit-code <reviewed-sha> <promoted-sha>`). If the SHA changed, record the actual `main` SHA and recheck the required artifacts, runtime equivalence and approval before tagging; if any executable inputs changed, rerun the affected live gates.
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
