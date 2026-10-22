# Security checks: the authorized-root boundary

Date: 2026-10-21 (Asia/Hong_Kong)
Code: commit `64ad2ed` (branch `Role_A`)
Runtime for the end-to-end part: Docker Compose stack, images built from that
commit on Windows 11 + Docker Desktop.
Runtime for the route-level part: `pytest` with the SQLite fixture in
`tests/conftest.py` (no PostgreSQL, no worker).

## What is being protected

Two separate promises, tested separately:

1. **Nothing outside the authorized scope is ever read.** The mount allowlist
   decides which container paths exist at all; canonical containment decides
   which relative path inside a mount is reachable; the authorized root narrows
   it once more.
2. **Nothing is ever written to the source tree.** The mounts are `:ro`, and the
   API and worker only open files for reading. Evidence for this is the
   before/after hash in the last section.

## Rejection cases

Every row is a test that asserts a specific refusal, not merely "no crash".

| # | Attempt | Test | Result |
| --- | --- | --- | --- |
| 1 | Root path `..` | `test_a_root_pointing_outside_the_mount_is_rejected[..]` | PASS |
| 2 | Root path `/etc` (absolute) | `test_a_root_pointing_outside_the_mount_is_rejected[/etc]` | PASS |
| 3 | Root path `regression/../../escape` | `test_a_root_pointing_outside_the_mount_is_rejected[regression/../../escape]` | PASS |
| 4 | Unknown `mount_id` on `POST /roots` | `test_an_unknown_mount_is_a_404_with_a_machine_readable_code` | PASS - `404 unknown_mount` |
| 5 | Escaping `relative_path` on `POST /roots` | `test_a_path_escaping_the_mount_is_a_403_path_out_of_scope` | PASS - `403 path_out_of_scope` |
| 6 | Unknown mount on `GET /mounts/{id}/directories` | `test_directories_of_an_unknown_mount_is_a_coded_404` | PASS - `404 unknown_mount` |
| 7 | Escaping `relative_path` on `GET /mounts/{id}/directories` | `test_directories_reject_a_path_escaping_the_mount` | PASS - `403 path_out_of_scope` |
| 8 | Scanning a revoked root | `test_a_revoked_root_refuses_to_scan` | PASS |
| 9 | Rescanning a revoked root | `test_rescanning_a_revoked_root_is_refused` | PASS - `409 root_revoked` |
| 10 | Resolving a source path for new work on a paused root | `test_resolving_a_source_path_refuses_a_paused_root_for_new_work` | PASS |
| 11 | Resolving a source path for a read on a paused root | `test_resolving_a_source_path_allows_a_paused_root_for_reads` | PASS (positive control: reads stay allowed) |
| 12 | Resolving a source path on a revoking/revoked root | `test_resolving_a_source_path_refuses_a_revoked_root_for_reads[revoking\|revoked]` | PASS |
| 13 | Symlinked directory inside the root | `test_a_symlinked_directory_inside_the_root_is_not_followed` | **SKIPPED on this host** |
| 14 | Root path that is itself a symlink outside the mount | `test_a_root_that_is_a_symlink_outside_the_mount_is_rejected` | **SKIPPED on this host** |
| 15 | Authorizing a paused root | `test_authorizing_a_paused_folder_is_refused` | PASS - `409 root_paused`, no job created |
| 16 | Authorizing a revoking root | `test_authorizing_a_revoking_folder_is_refused` | PASS - `409 root_revoking` |
| 17 | Retrying work for a paused / revoking / revoked root | `test_retrying_a_job_of_a_{paused,revoking,revoked}_root_is_refused` | PASS - 409 with the matching code, job left `failed` |
| 18 | Retrying an embed job whose root was revoked | `test_retrying_an_embed_job_finds_its_root_through_the_version` | PASS - the root is resolved through `version_id` |
| 19 | Two rescans of one root at the same time | `test_concurrent_rescans_queue_exactly_one_scan` (PostgreSQL) | PASS - one 202, one `409 active_job_exists`, exactly one live job |

## Why cases 13-14 are skipped, and what that means

On this Windows machine `Path.symlink_to()` returns successfully but leaves no
symlink behind, so the two escape tests would pass while exercising nothing.
The fixture now asserts `is_symlink()` after creating the link and skips when
the platform lies; a silent false pass would be worse than a visible skip.

Consequence, stated plainly: **symlink-escape rejection is implemented
(`_contained()` resolves before comparing, and traversal skips `is_symlink()`
entries) but is not verified by execution on this host.** It must be re-run on
Linux (CI or a container) before the claim is made. The code path lives in
`services/scan/handler.py` -> `_contained()` and `_iter_source_files()`.

## Original files unchanged

The end-to-end run hashed the host copy of the corpus before and after a scan
plus a rescan (`scripts/w7_evidence_probe.py`):

- files hashed: 18 (the 16 mounted fixtures plus `parsing/normal.pdf` and
  `relations/entities.pdf`, which are not mounted)
- changed: 0
- missing: 0

## Reproduce

```bash
python -m pytest tests/unit/test_scan_handler.py \
  tests/integration/test_api_w7_routes.py \
  tests/integration/test_api_integration.py -q
# 48 passed, 2 skipped (the two symlink cases above)
```

The end-to-end half:

```bash
docker compose up -d --build
python scripts/w7_evidence_probe.py --out submissions/week07/evidence/scan-run.json
```

The PostgreSQL concurrency case needs a database:

```bash
SEARCH_TEST_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:15432/maie6000c" \
  pytest tests/integration/test_api_queue_postgres.py -q
```

## Known gaps

- Symlink escape (cases 13-14) unverified on this host; see above.
- Route-level checks use the SQLite fixture, so they prove the HTTP contract,
  not PostgreSQL behaviour. The compose stack covered the positive path only.
- No test yet for overlapping authorized roots, which R1 must reject; it is out
  of W7 scope but listed here so it is not mistaken for done.
