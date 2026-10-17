# W7 Demo Script

Target length: 3–4 minutes. The six steps below are the live path. Use the
recorded backup only if the local stack fails.

## Step 1 — State the promise and the boundary

“This is Team 11's read-only file retrieval assistant. We are not generating
an answer from the files. We are finding a passage in a folder the user has
authorized, and showing the exact file version and page it came from. The
folder in this demo is synthetic; the original files are mounted read-only.”

Show the local URL and the `corpus` mount. Do not use the mock adapter. The
screen should say `Local service mode` and show the API-backed directory
screen.

## Step 2 — Authorize a root and start a scan

Select the `corpus` mount and the root directory. Press **Authorize and start
scan**. Point out the response state: the API returns `202 Accepted` with a
`root_id` and an integer `job_id`; it does not parse files inside the HTTP
request.

Show the progress page. Wait for the scan job to complete, then read the
counts aloud:

- 16 files seen;
- 16 current versions;
- 12 files `basic_ready`;
- 0 failed;
- 4 abnormal or unsupported records with explicit reasons.

Say: “A completed scan is not the same as a parsed corpus. The worker creates
separate extraction jobs, and those jobs update the version state and the
root's file-stage counters.”

## Step 3 — Search for a known passage

Open Search & Discover. Type:

```text
Team 11 synthetic document 01
```

The top result should be:

```text
normal/team-alpha/team11-demo-01.pdf
```

Point out the match reason and the page label:

```text
keyword: team, 11, synthetic, document, 01; phrase match
Page 1 · returned chunk
```

The result list may show other files because the synthetic corpus shares the
common phrase. The top ranked file is the specific expected document; the
system does not pretend that a shared phrase is unique.

## Step 4 — Open the source evidence

Select the result. The source inspector should show:

- file: `team11-demo-01.pdf`;
- relative path: `normal/team-alpha/team11-demo-01.pdf`;
- version id: `f3ec6956-c50f-4b50-a3d8-f1bd02ffd5e0`;
- page: `P1`;
- passage: `Team 11 synthetic document 01 | synthetic page 1 of 1`.

Say: “The search result and the evidence are tied to the same canonical chunk
id. We do not perform a second search and hope it returns the same passage.
The evidence route also checks that the version is current and the root is
still authorized.”

## Step 5 — Repeat the scan

Return to Directories & Jobs and authorize the same root again. Show the
second job completing. The root should still report 16 files and 16 versions.
The scanner reuses the same content versions and does not enqueue a duplicate
extraction job for a version that is already current.

If the UI is still polling, explain that the client displays the committed
state and never sets `running` or `completed` itself. The worker owns those
transitions.

## Step 6 — Show an honest failure and the fallback

Open the needs-attention filter. Point at one abnormal PDF and the unsupported
DOCX. Read the reason codes rather than calling every item a parser bug:

- a damaged or truncated PDF is `corrupt` or `truncated`;
- an empty or image-only PDF is `no_text_layer`/`empty`;
- a DOCX is `unsupported_format`.

Then show the search telemetry line. In this checkout it says keyword search
and semantic not connected. Explain: “The semantic index and embedding
interface are implemented, but the pinned E5 model is not in the release
bundle. The system degrades to keyword search and says so. We do not count a
keyword result as a semantic success.”

Finally, state the reliability behavior: “The worker records a lease and a
worker identity, retries transient failures with bounded backoff, and returns
an expired claim to `retry_wait`. A failed job also has an explicit retry
button. We have not yet load-tested multiple competing workers.”

## Closing

“The verified path is: authorized folder → durable scan → parsed pages →
current-version keyword search → source/page evidence. The originals remain
read-only, the failures are visible, and every successful result has a source
we can open.”
