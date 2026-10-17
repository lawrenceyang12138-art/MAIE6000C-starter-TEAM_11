# W07 M1 backend verification on the integration branch (2026-10-17)

Branch: `w7-integration-bootstrap`  
Runtime: fresh Docker Compose project with a new PostgreSQL volume  
Corpus: D's frozen 16-file corpus copied without the manifest file

## Verified result

| Check | Result |
| --- | --- |
| `GET /mounts` | the `corpus` mount is present and available |
| `POST /roots` | HTTP 202 with flat `root_id`, integer `job_id`, pending status |
| Automatic scan worker | completed |
| Automatic extraction workers | 16 files processed |
| File count | **16** |
| Version count | **16** |
| `basic_ready` | **12** |
| unsupported/abnormal records | **4**, each with a non-empty reason code |
| Keyword queries K01-K05 | **5/5** at the expected file and page |
| Evidence after each query | **5/5** returned the same chunk page |
| Repeated scan | files **16**, versions **16**, no duplicates |
| Frozen corpus SHA-256 | **16 files, 0 mismatches** |

## Search rows

```text
K01 True True True
K02 True True True
K03 True True True
K04 True True True
K05 True True True
```

Columns are: query id, expected relative path, result page, evidence page.

## Meaning

This proves the backend M1 path:

```text
authorize root
→ durable scan_root job
→ worker creates files/current versions/extract_file jobs
→ parser stores page-located chunks
→ keyword search reads current authorized chunks
→ returned chunk id reads back the same stored evidence
```

It does not yet prove the final browser interaction: D's current results view
still performs a client-side filter and has not been wired to `POST /search`.
That remains the browser-level M1 gap.
