# B - Reading a passage back as current evidence (10.17 AM)

Owner: B (read files / PDF parsing and evidence quality)
Module: `services/parsing/evidence.py`

## What this adds

A search result is only trustworthy if the passage it shows is still the
current content of a file the user still authorises us to read. This module
serves one stored passage back, and refuses when it is no longer current.

Four checks, cheapest first:

1. the chunk exists
2. its file still points at this version as the current one
3. the file is still present
4. the authorised folder has not been revoked

Each refusal carries a reason code, because "no such passage" and "this passage
used to be valid" are different situations and the interface has to say which
one happened.

Check 2 has two ways to fail, and they are not the same thing:

- the file points at a **different** version: this passage is historical ->
  `version_superseded`
- the file points at **nothing**: no version has been marked current yet ->
  `no_current_version`

Those were one code until 2026-10-15. Reporting the second as the first told
whoever was debugging that "the file has newer content" when there was no newer
content, which sends them looking for a version that does not exist.

## End-to-end run against real PostgreSQL

A real 22-page PDF was parsed, chunked and stored, then passages were read back
by chunk id.

| Step | Observed |
| --- | --- |
| 1. Extraction handler | `basic_ready` |
| 2. Chunks stored | 24 |
| 3. Read back, first six | page 1 chunk 1, page 2 chunk 2, page 3 chunk 3, page 4 chunk 4, page 5 chunk 5, page 6 chunk 6 |
| 4. After revoking the folder | refused, `reason_code = root_revoked` |

Step 3 returns the page each passage actually came from, which is the
"click through and land on the right page" behaviour the demo depends on.
Step 4 is the point of the module: revoking authorisation immediately stops the
passage being served, without deleting anything.

## Automated verification

Command:

```
docker compose run --rm --no-deps api pytest -q tests/unit/test_parsing_evidence.py
```

Result: **8 passed**.

- a current passage comes back with its page, ordinal, path and content hash
- an unknown chunk id is refused with `chunk_not_found`
- a superseded version is refused with `version_superseded`
- a file with no current version at all is refused with `no_current_version`,
  and the two messages are asserted to differ
- a missing file is refused with `file_missing`
- a revoked folder is refused with `root_revoked`
- **ten passages resolve to the page they were stored on**, which is the
  page-location sample set the schedule asks for

Full suite at this commit: **47 passed, 1 skipped**. `ruff check .` clean.

## An open interface question for A

The file's `current_version_id` is what makes a passage "current". **Nothing in
B's code sets it**, and it is not set by the extraction handler - extraction
processes a version that scanning already decided exists.

Who sets `current_version_id` needs to be agreed:

- the scan step, when it observes new content, or
- the extraction handler, once a version reaches `basic_ready`

Until it is set, `read_evidence` correctly refuses everything, and it now says
why in terms that name the actual problem: `no_current_version`, not
"superseded". The end-to-end run above set it by hand to exercise the path.
This is a boundary to settle with A before the search endpoint is wired up,
otherwise every search result will look expired - and, with the old collapsed
code, would have blamed content that does not exist.

## What is still not here

- **No HTTP endpoint.** This is the handler an API route will call; the route
  belongs to A.
- **No on-disk fingerprint check.** The checks are all database-level. The
  architecture proposal asks for verifying the file's fingerprint before
  serving a preview, which needs a resolved source path from A's mount
  allowlist.
  Known open item.
- **No search ranking.** Selecting which passages to offer is C's work; this
  module only serves one passage once it has been chosen.
