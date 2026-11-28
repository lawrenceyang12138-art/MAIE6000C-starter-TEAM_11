# Scan idempotency

Date: 2026-10-21 (Asia/Hong_Kong)
Code: commit `64ad2ed` (branch `Role_A`)
Environment: Docker Compose (api / worker / ai / db with pgvector) built from
that commit, Windows 11 host, client Python 3.11.17.

## The claim under test

Repeated scans of the same authorized folder must not duplicate files, content
versions or extraction jobs (contract 2.2 and 3.4.6). Unchanged content reuses
its existing `file_versions` row; the `current_version_id` pointer still has to
name the bytes on disk.

## Observed result

Root `ecb84a43-31e2-40a0-8b3c-38687d56541b`, mount `corpus`, path `.`, scanned
five times in total: once when the root was authorized, then twice in each of
two probe runs (job ids 30/31 and 32/33).

| Measure | Value | Meaning |
| --- | --- | --- |
| `files` rows | 16 | one per fixture, none duplicated |
| `file_versions` rows | 16 | **one per file across five scans** |
| `extract_file` jobs | 16, all `completed` | one per version, no re-dispatch |
| `embed_file` jobs | 12, all `completed` | only after `basic_ready` |
| `scan_root` jobs | 5, all `completed` | the five scans themselves |
| new file rows on the last rescan | 0 | `GET /files` before/after |
| `file_counts` unchanged | true | 16 total, 12 `basic_ready`, 4 `unsupported` |

16 versions after 5 scans is the whole point: had the handler created a version
per observation, this number would be 80.

The same holds across both roots used in this milestone. Direct database
counts after eleven scans in total:

```text
roots    |  2
files    | 29
versions | 29
```

29 files (16 + 13) and 29 versions: exactly one version per file no matter how
many times the folder was scanned.

Stage breakdown of the current versions (from `GET /roots/{root_id}`):

```json
{"total": 16, "discovered": 0, "extracting": 0, "basic_ready": 12,
 "enriched": 0, "failed": 0, "unsupported": 4}
```

The four `unsupported` versions carry explicit reasons instead of silently
disappearing (see `m1-catalog.md`): `corrupt`, `encrypted`, `no_text_layer`,
`unsupported_format`.

## Commands actually run

```bash
docker compose up -d --build
python scripts/w7_evidence_probe.py --out submissions/week07/evidence/scan-run.json

docker compose exec -T db psql -U postgres -d maie6000c -c "
select 'files' as what, count(*) from files where root_id='ecb84a43-31e2-40a0-8b3c-38687d56541b'
union all select 'versions', count(*) from file_versions
where file_id in (select id from files where root_id='ecb84a43-31e2-40a0-8b3c-38687d56541b');"

docker compose exec -T db psql -U postgres -d maie6000c -c "
select job_type, status, count(*) from jobs
where root_id='ecb84a43-31e2-40a0-8b3c-38687d56541b'
or version_id in (select id from file_versions
where file_id in (select id from files where root_id='ecb84a43-31e2-40a0-8b3c-38687d56541b'))
group by 1,2 order by 1,2;"
```

The probe talks to the public API only; the two `psql` queries exist because
the API deliberately does not expose version or job totals.

## Retry is not a second chance to reset finished work

A retry only acts on a job that is still `failed`. The status read at the top of the
request can be stale by the time the row is written, so the transition is a conditional
`UPDATE ... WHERE id = :id AND status = 'failed'` and the request is refused unless exactly
one row moved. Four PostgreSQL cases cover it: a scan job and a version-targeted job,
each under a worker claim and a worker completion. Each asserts that the refused request
leaves the status, `claimed_at`, `completed_at` and `attempts` untouched and that the
worker finds nothing claimable afterwards. Removing the `status = 'failed'` clause makes
all four fail, which is the check that the test is measuring the guard rather than the
happy path.

## Cases that are unit-level, not end-to-end

The compose mount is read-only by design, so content cannot be edited inside
the stack. These behaviours are covered by tests against real temporary
directories instead, and must be quoted as unit-level evidence:

| Case | Test | What it asserts |
| --- | --- | --- |
| Content changes | `test_changed_content_versions_anew_and_moves_the_pointer` | one new version, pointer moves, old row retained |
| Content reverts to an earlier revision | `test_reverting_to_earlier_content_moves_the_pointer_back` | pointer moves back, `versions_created == 0`, version count unchanged |
| Revert does not requeue finished work | `test_a_revert_does_not_redispatch_a_processed_version` | `jobs_dispatched == 0` |
| Revert recovers a version that never ran | `test_a_revert_redispatches_a_version_that_never_finished` | exactly one new extract job |
| File disappears | `test_a_missing_file_keeps_the_pointer_on_the_last_observed_version` | presence `missing`, pointer kept |
| Second scan stands down while one is live | `test_a_second_scan_of_a_live_root_is_skipped` | outcome `skipped`, nothing written |

Command: `python -m pytest tests/unit/test_scan_handler.py -q` -> 17 passed,
2 skipped (the two symlink cases, see `security-check.md`).

## Limits

- The whole-mount root (`ecb84a43…`) already existed from the earlier PR #3 run,
  so its five scans prove repeat idempotency rather than a first import. The
  first import is covered by the fresh `regression` root in `m1-catalog.md`.
- Version and job totals come from manual `psql`, not from a product endpoint.
- Nothing here covers PostgreSQL restart behaviour; that is `restart-v1.md`.
