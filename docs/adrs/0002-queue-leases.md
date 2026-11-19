# ADR 0002 — Queue leases and crash recovery

## Status

Proposed (2026-11-19)

## Context

`jobs` is the only durable queue. The worker claims work with `claim_next_pending_job`,
which selects the oldest `pending` row and flips it to `claimed` in one transaction.
That is correct for one process and has two gaps:

1. **A crash strands work.** If the worker dies after the commit in `claim_next_pending_job`
   and before the handler finishes, the row stays `claimed` forever. Nothing re-claims it:
   the claim query only looks at `pending`. The only recovery today is a manual
   `POST /jobs/{id}/retry`, which is a human-in-the-loop tool, not a durability property.
2. **One worker only.** Two workers are safe against duplicate *claims* (the claim is a
   single transaction), but there is no lease, so a second worker cannot distinguish
   "someone is working on this" from "someone died holding this". The contract already
   lists single-worker scope as a W7 limit.

The retry path also has no pacing: a job that fails for a transient reason is retried as
soon as a human asks, with `attempts` as the only record.

## Decision

Add a lease to `jobs` and make the claim condition cover both `pending` work and expired
`claimed` work.

- New nullable columns on `jobs`: `lease_owner` (text), `lease_expires_at` (timestamptz),
  `not_before` (timestamptz, default null). Additive migration, no backfill.
- Claim becomes one conditional update:

  ```sql
  UPDATE jobs SET status='claimed', lease_owner=:owner,
                  lease_expires_at=now() + :ttl, claimed_at=now(), attempts=attempts+1
   WHERE id = (
     SELECT id FROM jobs
      WHERE (status='pending' AND (not_before IS NULL OR not_before <= now()))
         OR (status='claimed' AND lease_expires_at < now())
      ORDER BY created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1)
  RETURNING id;
  ```

- The worker renews its lease every `ttl/3` while a job runs and releases it on completion
  or failure (`lease_owner = NULL`).
- An expired lease is claimed by the same statement, so recovery needs no sweeper process.
  `attempts` already counts recoveries, and `POST /jobs/{id}/retry` keeps its conditional
  `status='failed'` update from PR #6.
- Failure scheduling uses `not_before = now() + backoff(attempts)` with capped exponential
  growth; the retry route may still force an immediate retry.
- `/metrics` gains queue depth, claimed-but-expired count, job duration histogram and
  attempts distribution.

## Consequences

- A job can run twice when a lease expires while the original worker is still alive (a long
  GC pause or a suspended laptop). Handlers must therefore be idempotent, and two are not
  yet:
  - `handle_scan_root` is idempotent by content hash (verified in `scan-idempotency.md`);
  - `embed_version` replaces the sidecars for a version, which is idempotent;
  - `handle_extract_file` **replaces chunks**, and reviews/evidence hang off stable chunk
    ids. A duplicate extract would detach existing reviews. The lease work must either
    skip extraction when the version is already `basic_ready`/`enriched` (the PR #6 retry
    branch already does this) or make chunk replacement id-preserving.
- Two workers become supported; the "single worker" scope note in the contract is removed
  and replaced by a lease definition (ttl, renewal, recovery).
- The API surface does not change: `GET /jobs/{id}` keeps reporting `pending/running/
  completed/failed`. `lease_owner` stays internal so the public vocabulary does not grow.
- One migration, additive and reversible: dropping the three columns restores the current
  behaviour exactly.

## Alternatives considered

- **Advisory locks in PostgreSQL** (`pg_try_advisory_lock`). Clean, but the lock dies with
  the connection, so a half-finished job becomes claimable the moment the socket closes —
  which is the crash case we are trying to recover deliberately, with accounting.
- **An external broker** (Redis/SQS). Correct, but adds a service to a local single-host
  product whose durability story is already PostgreSQL.
- **A separate sweeper process.** Works, but duplicates the claim predicate in two places;
  folding expiry into the claim keeps one definition of "claimable".

## Rollout

1. Migration (additive), no behaviour change: columns exist, claim still ignores them.
2. Worker writes leases and renews; claim starts honouring `lease_expires_at`. Single
   worker unaffected.
3. Tests: two workers, no duplicate execution; kill a worker mid-job and assert recovery
   after ttl; assert `attempts` increments and the backoff is applied.
4. Docs: contract section 8 (job states) and `docs/operations.md` gain the lease definition
   and the recovery procedure.

## Open questions

- ttl: 60 s is the working guess (longest observed embed batch is a few seconds), renewed
  every 20 s.
- Max attempts before a job is parked as `failed` with `error_code = retry_exhausted`.
- Whether `not_before` should be exposed in `GET /jobs/{id}` as `retry_at`, or stay internal
  until a UI needs it.
