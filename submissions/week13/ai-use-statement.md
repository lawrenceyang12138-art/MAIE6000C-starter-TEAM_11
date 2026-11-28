# AI Use Statement · MAIE 6000C Team 11

## Tools and purpose

- **OpenAI Codex (generative AI):** Role D used it to compare the course evidence with the team release plan, inspect the current search/evidence contract, implement and test the limited frontend change, prepare the offline PDF cue card, and draft the W13 README, brief, runbook, evidence index and release checklist.
- **OpenAI Codex, as disclosed by Role C:** assisted search-validation implementation, fixture drafting, test execution and report preparation. The disclosure is in the [archived Role C contribution](https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11/blob/16251df8b1167a740d7f29863144a3859a65e4b9/submissions/week13/sections/C.md#remaining-human-decisions-and-limitations); the [canonical dated validation record](../../docs/search-validation.md#2026-11-23-validation-results) gives the runtime, dataset, results and limits.

The application's local PPLX embedding model is part of the product, not the generative tool used to write this statement. This draft does not make personal declarations about A or B's tool use; capture their actual material use or confirmation before final approval.

## Affected work, checks and decisions

- Role D's affected work is the search result/inspector path, the frontend allowlist for B's documented rejection codes, the focused tests, and the W13 artifact package. Source selection, ranking, parser scope and the model were not expanded for this task.
- The preparation checked the course instructions against the supplied assignment screenshot and HTML export and the browser fields against repository code. It also compared A's [candidate record](../../docs/w13-final-candidate.md) with the merged revision; A's Worker/API verification does not cover D's local frontend patch. The [evidence index](evidence/README.md) identifies checks actually performed, their setup and their limits. A fixture or frontend test is not a browser/API/Worker sign-off on the assembled release.
- We excluded fake page numbers, a new preview, mock or historical output as current acceptance, and any unverified format from the support list. The fallback presentation is explicitly an offline cue card, not a fabricated recording or a demonstration of live AI.

## Responsibility

The team is responsible for verifying and being able to explain the submitted code and documentation, approving this disclosure, and confirming that the supported claims match the tagged commit. Team approval and any individual attestations remain pending; Codex did not sign, push a tag or submit on anyone's behalf.
