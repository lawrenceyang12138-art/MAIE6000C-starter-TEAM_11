"""PostgreSQL concurrency test for the queue invariant.

SQLite serialises writers by locking the whole database, so the interleaving
this guards against cannot be reproduced there: two requests can both read "no
live scan" and both enqueue one. This test uses two real PostgreSQL sessions and
a barrier so both requests reach the check together.

Run it with ``SEARCH_TEST_DATABASE_URL`` pointing at a PostgreSQL database:

    SEARCH_TEST_DATABASE_URL=postgresql+psycopg://... pytest \
        tests/integration/test_api_queue_postgres.py -q
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text

from services.api.app import main as api_main
from services.api.app.main import create_root_with_scan_job, rescan_root, retry_job
from services.common.db import Base, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
    VersionStatus,
)
from services.worker.app import main as worker_main

pytestmark = pytest.mark.postgres

# How long the losing request is allowed to wait for the winner's lock. Large
# enough to ride out a slow CI machine, small enough to fail fast on a deadlock.
LOCK_WAIT_SECONDS = 0.2


@pytest.fixture()
def queue_factory():
    """A session factory bound to a throwaway schema."""
    url = os.getenv("SEARCH_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SEARCH_TEST_DATABASE_URL not set")

    schema = "w7_queue_test_" + uuid.uuid4().hex

    # The schema is set through the connection options rather than a ``SET`` in
    # a connect listener: ``SET`` runs inside an implicit transaction, and the
    # pool's rollback-on-return discards it, leaving later sessions reading
    # ``public``. Connection options are applied by the server at startup.
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "options": f"-c search_path={schema},public",
            # Fail fast when the database is down instead of hanging the suite.
            "connect_timeout": 5,
        },
    )

    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = connection.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(scoped)

    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _seed_root(factory) -> str:
    with factory() as db:
        root = AuthorizedRoot(
            mount_id="queue-" + uuid.uuid4().hex[:8],
            relative_path=".",
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        db.commit()
        return root.id


def _live_scan_count(factory, root_id: str) -> int:
    with factory() as db:
        return db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.root_id == root_id,
                Job.job_type == RootJobType.SCAN_ROOT.value,
                Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
            )
        ).scalar_one()


def test_concurrent_rescans_queue_exactly_one_scan(queue_factory, monkeypatch):
    """Two rescans that both observe "no live scan" must still queue one job.

    The barrier only aligns the start. On its own that is not enough: the window
    between the check and the enqueue is microseconds, so the requests would
    serialise by luck rather than by design and the test would pass with the
    lock removed. The patched check therefore sleeps after looking, which widens
    that window to something reproducible. With the row lock the second request
    cannot reach the check at all until the first has committed, so the widened
    window never contains two readers.
    """
    root_id = _seed_root(queue_factory)
    barrier = threading.Barrier(2, timeout=10)
    outcomes: list[object] = []
    collect = threading.Lock()

    real_check = api_main._active_scan_job

    def slow_check(db, root_id_inner):
        found = real_check(db, root_id_inner)
        if found is None:
            time.sleep(LOCK_WAIT_SECONDS)
        return found

    monkeypatch.setattr(api_main, "_active_scan_job", slow_check)

    def attempt() -> None:
        with queue_factory() as db:
            barrier.wait()
            try:
                outcome: object = rescan_root(root_id, db)
            except HTTPException as exc:  # the loser must be refused, not crash
                outcome = exc
            with collect:
                outcomes.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    accepted = [item for item in outcomes if not isinstance(item, HTTPException)]
    refused = [item for item in outcomes if isinstance(item, HTTPException)]

    assert len(accepted) == 1, f"expected one accepted rescan, got {outcomes}"
    assert len(refused) == 1, f"expected one refusal, got {outcomes}"
    assert refused[0].status_code == 409
    assert refused[0].detail["code"] == "active_job_exists"
    # The loser learns which job won, so it can attach instead of retrying.
    assert refused[0].detail["job_id"] == accepted[0].job_id
    assert refused[0].detail["root_id"] == root_id

    assert _live_scan_count(queue_factory, root_id) == 1


def test_concurrent_authorizations_create_one_root_and_one_scan(queue_factory, monkeypatch):
    """Two simultaneous authorizations of one folder must not create two roots.

    The loser hits the unique constraint on ``(mount_id, relative_path)``. It
    must recover into the existing root and answer a scan conflict rather than
    surface an integrity error, and the folder must end up with exactly one live
    scan.
    """
    mount_id = "authorize-" + uuid.uuid4().hex[:8]
    barrier = threading.Barrier(2, timeout=10)

    # Same widening trick as above, on the lookup instead of the scan check: both
    # requests must decide "this folder is unknown" before either inserts, which
    # is the only way to reach the unique-constraint recovery path.
    real_find = api_main._find_root

    def slow_find(db, mount_id_inner, relative_path):
        found = real_find(db, mount_id_inner, relative_path)
        time.sleep(LOCK_WAIT_SECONDS)
        return found

    monkeypatch.setattr(api_main, "_find_root", slow_find)
    outcomes: list[object] = []
    collect = threading.Lock()

    def attempt() -> None:
        with queue_factory() as db:
            barrier.wait()
            try:
                root, job = create_root_with_scan_job(db, mount_id, ".")
                outcome: object = (root.id, job.id)
            except HTTPException as exc:
                outcome = exc
            with collect:
                outcomes.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    accepted = [item for item in outcomes if isinstance(item, tuple)]
    refused = [item for item in outcomes if isinstance(item, HTTPException)]

    assert len(accepted) == 1, f"expected one authorization, got {outcomes}"
    assert len(refused) == 1, f"expected one refusal, got {outcomes}"
    assert refused[0].status_code == 409
    assert refused[0].detail["code"] == "active_job_exists"
    assert refused[0].detail["root_id"] == accepted[0][0]
    assert refused[0].detail["job_id"] == accepted[0][1]

    with queue_factory() as db:
        roots = db.execute(
            select(func.count())
            .select_from(AuthorizedRoot)
            .where(AuthorizedRoot.mount_id == mount_id)
        ).scalar_one()
    assert roots == 1, "the unique constraint must leave exactly one root"
    assert _live_scan_count(queue_factory, accepted[0][0]) == 1


def _seed_failed_job(factory, job_kind: str) -> int:
    """A failed job that a retry could legitimately pick up."""
    with factory() as db:
        root = AuthorizedRoot(
            mount_id="retry-" + uuid.uuid4().hex[:8],
            relative_path=".",
            status=RootStatus.ACTIVE.value,
        )
        db.add(root)
        db.flush()
        if job_kind == "scan":
            job = Job(
                root_id=root.id,
                job_type=RootJobType.SCAN_ROOT.value,
                status=JobStatus.FAILED.value,
            )
            db.add(job)
            db.commit()
            return job.id

        record = FileRecord(
            root_id=root.id, relative_path="retry.pdf", name="retry.pdf"
        )
        db.add(record)
        db.flush()
        version = FileVersion(
            file_id=record.id,
            content_sha256="e" * 64,
            byte_size=10,
            status=VersionStatus.DISCOVERED.value,
        )
        db.add(version)
        db.flush()
        job = Job(
            version_id=version.id,
            job_type=RootJobType.EMBED_FILE.value,
            status=JobStatus.FAILED.value,
        )
        db.add(job)
        db.commit()
        return job.id


@pytest.mark.parametrize("job_kind", ["scan", "embed"])
@pytest.mark.parametrize("winner_state", ["claimed", "completed"])
def test_a_stale_retry_cannot_reset_work_already_taken(
    queue_factory, monkeypatch, job_kind, winner_state
):
    """A retry that read the job before the lock must not undo later work.

    The loser reads the job while it is still ``failed``, then parks before
    taking the root lock. The winner completes a normal retry, and the job moves
    on - claimed by the worker, or completed. When the loser resumes it must be
    refused: writing ``pending`` over claimed/completed work would clear the
    timestamps and make a finished job run twice.
    """
    job_id = _seed_failed_job(queue_factory, job_kind)
    read_done = threading.Event()
    release_loser = threading.Event()
    real_root_for_job = api_main._root_for_job

    def gated_root_for_job(db, job):
        root = real_root_for_job(db, job)
        if threading.current_thread().name == "loser":
            read_done.set()
            release_loser.wait(timeout=15)
        return root

    monkeypatch.setattr(api_main, "_root_for_job", gated_root_for_job)

    outcomes: dict[str, object] = {}

    def attempt(name: str) -> None:
        with queue_factory() as db:
            try:
                outcomes[name] = retry_job(job_id, db)
            except HTTPException as exc:
                outcomes[name] = exc

    loser = threading.Thread(target=attempt, args=("loser",), name="loser")
    loser.start()
    assert read_done.wait(15), "the loser never reached the lock boundary"

    winner = threading.Thread(target=attempt, args=("winner",), name="winner")
    winner.start()
    winner.join(timeout=30)
    assert isinstance(outcomes.get("winner"), object)
    assert not isinstance(outcomes["winner"], HTTPException), outcomes["winner"]

    with queue_factory() as db:
        if winner_state == "claimed":
            claimed = worker_main.claim_next_pending_job(db)
            assert claimed is not None and claimed.id == job_id
        else:
            finished = db.get(Job, job_id)
            worker_main._complete_job(db, finished)

    with queue_factory() as db:
        before = db.get(Job, job_id)
        status_before = before.status
        claimed_at = before.claimed_at
        completed_at = before.completed_at
        attempts_before = before.attempts
    assert status_before == winner_state

    release_loser.set()
    loser.join(timeout=30)

    refused = outcomes.get("loser")
    assert isinstance(refused, HTTPException), f"the loser was not refused: {refused}"
    assert refused.status_code == 409
    assert refused.detail["code"] == "job_not_retryable"

    with queue_factory() as db:
        after = db.get(Job, job_id)
        assert after.status == status_before, "the stale retry rewrote the status"
        assert after.claimed_at == claimed_at, "the stale retry cleared claimed_at"
        assert after.completed_at == completed_at, "the stale retry cleared completed_at"
        assert after.attempts == attempts_before
        # Nothing was requeued, so the worker finds no claimable work.
        assert worker_main.claim_next_pending_job(db) is None
