# ADR 0002 — Queue leases and crash recovery

## Status

Accepted (2026-11-19); backoff deferred. Verified against the Compose stack the same day: two concurrent claimers produced exactly one winner, and a lease left behind by a dead owner was reclaimed by the worker with attempts=2 and released on completion.

## Context

`jobs` is the only durable queue. Before leases, the worker selected the oldest
`pending` row and flipped it to `claimed` in one transaction. That prevented
duplicate claims, but a row left by a dead worker looked the same as a job in
progress. The claim query only looked at `pending`; the manual retry endpoint
for `failed` jobs could not recover an abandoned claim. The W7 implementation
was consequently scoped to one worker.

## Decision

Keep the PostgreSQL queue and add cooperative leases. Make both pending and
expired-lease jobs eligible for the same claim path.

- The [worker](../../services/worker/app/main.py) selects the oldest eligible job
  and conditionally claims it in the same transaction. PostgreSQL uses
  `FOR UPDATE SKIP LOCKED` at selection. The update repeats the eligibility
  predicate and returns the new attempt and owner. Reclaiming increments
  `attempts` without needing a separate sweeper.
- [Migration 0006](../../alembic/versions/20261119_0006_add_job_leases.py) adds
  two nullable fields, `lease_owner` and indexed `lease_expires_at`. The worker
  grants a 60-second lease, renews it every 20 seconds and clears it at the end of
  the attempt.
- Keep `POST /jobs/{id}/retry` for jobs already marked `failed`. It clears the
  lease. Backoff, scheduled retries and a `not_before` field remain deferred.

## Consequences

- If a worker resumes after its lease expires, some computation can run twice.
  This is not exactly-once execution. Guarded transactions refuse stale attempts
  when they try to publish results or set a terminal state.
- The lease adds heartbeat writes and recovery waits for expiry. The two-claimer
  test establishes a single winner, not multi-worker throughput.
- The API still reports `pending`, `running`, `completed` and `failed`. Both
  lease fields stay internal. Operators can inspect the queue using the
  [operations guide](../operations.md#5-failures-and-retry); the proposed
  queue-specific Prometheus metrics were not added.

## Alternatives considered

- **Advisory locks in PostgreSQL** (`pg_try_advisory_lock`). Clean, but the lock dies with
  the connection, so a half-finished job becomes claimable the moment the socket closes —
  which is the crash case we are trying to recover deliberately, with accounting.
- **An external broker** (Redis/SQS). Correct, but adds a service to a local single-host
  product whose durability story is already PostgreSQL.
- **A separate sweeper process.** Works, but duplicates the claim predicate in two places;
  folding expiry into the claim keeps one definition of "claimable".

## Rollout

[Migration 0007](../../alembic/versions/20261119_0007_recover_legacy_job_claims.py)
assigns a deadline to legacy `claimed` rows that have none, so the next worker
poll can reclaim them. Stop or drain pre-lease workers before upgrading; they do
not renew leases and must not share a rolling deployment with the new workers.
0006's schema downgrade removes the index and two fields; 0007's data correction
has no reverse operation. See the [job contract](../team11-w7-shared-contract.md#32-job-states)
and [operations guide](../operations.md#5-failures-and-retry).
