# Normal PDF browser evidence

This folder records two real browser runs against `http://127.0.0.1:13001`, using
the read-only `scenarios` mount and its `normal12` directory. Neither run used
HTTP interception or injected application data. Local AI was unavailable.

- `browser-live-first-import-report.json`: the original first import reached
  12 `basic_ready` files, zero failures and zero unsupported files. Its first
  keyword search for `invoices` returned no results. This exposed a gap between
  publishing `basic_ready` and completing keyword indexing. The failed run is
  retained, together with `00-first-import-progress.png` and `failure.png`.
- `browser-live-report.json`: a later authorization of the existing root and
  rescan passed three browser cases. It made one search attempt, found the real
  passage, retrieved the same chunk as source evidence, and preserved all 12
  file and version IDs across the rescan. No page errors were observed.

The later run proves retrieval, evidence and rescan behavior for existing data.
It does not establish that the first-import indexing gap has been fixed; that
requires the separate fresh-directory browser run against the repaired image.

The passing run used:

```powershell
node scripts/verify_w7_browser.mjs --ui http://127.0.0.1:13001 --mount scenarios --directory normal12 --expected-files 12 --expected-unsupported 0 --skip-relations --query invoices --output submissions/week07/evidence/20261031-w7/frontend-live-normal
```

The PNG files were visually inspected. They remain local under the repository's
existing evidence-screenshot ignore rule. In this run's `03` screenshot, the UI
had not yet polled the completed scan job and still displayed `Pending`; the
JSON contains the completed API state. The verifier now waits for the UI's
`Scan complete` badge before capturing subsequent scan screenshots.
