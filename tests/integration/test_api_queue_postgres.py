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
from services.api.app.main import create_root_with_scan_job, rescan_root
from services.common.db import Base, make_session_factory
from services.common.models import (
    AuthorizedRoot,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
)

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
        connect_args={"options": f"-c search_path={schema},public"},
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
