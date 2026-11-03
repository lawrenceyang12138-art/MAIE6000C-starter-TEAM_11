"""Mount reconnects must never strand a committed claim or lose queued work."""

from sqlalchemy import select

from services.common.db import make_session_factory
from services.common.models import Case, Job, JobStatus, JobType
from services.worker.app import main as worker


def queue(db, count=2):
    case = Case(title="Local folder check", description="Keep the queued work during reconnect.")
    db.add(case)
    db.flush()
    jobs = [Job(case_id=case.id, job_type=JobType.TRIAGE_CASE.value,
                status=JobStatus.PENDING.value) for _ in range(count)]
    db.add_all(jobs)
    db.commit()
    return [job.id for job in jobs]


def configure(db, monkeypatch):
    factory = make_session_factory(db.get_bind())
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    monkeypatch.setattr(worker, "recover_after_model_ready", lambda **kwargs: False)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)
    return factory


def statuses(db):
    db.expire_all()
    return list(db.scalars(select(Job.status).order_by(Job.id)))


def test_drain_before_claim_leaves_queue_untouched(db_session, monkeypatch):
    queue(db_session)
    configure(db_session, monkeypatch)
    drain = worker.DrainRequest()
    drain.request()
    worker.run_worker(drain=drain)
    assert statuses(db_session) == ["pending", "pending"]


def test_signal_during_claim_finishes_claim_and_restart_continues_queue(db_session, monkeypatch):
    ids = queue(db_session)
    factory = configure(db_session, monkeypatch)
    drain = worker.DrainRequest()
    original_claim = worker.claim_next_pending_job
    processed = []

    def claim(db):
        job = original_claim(db)
        drain.request()  # Exactly after the claim has committed.
        return job

    def process(job_id):
        with factory() as db:
            job = db.get(Job, job_id)
            assert job.status == "claimed"
            job.status = "completed"
            db.commit()
        processed.append(job_id)

    monkeypatch.setattr(worker, "claim_next_pending_job", claim)
    monkeypatch.setattr(worker, "process_job", process)
    worker.run_worker(drain=drain)
    assert processed == [ids[0]]
    assert statuses(db_session) == ["completed", "pending"]

    # A new worker receives a new drain request, and finishes the retained job.
    drain = worker.DrainRequest()
    worker.run_worker(drain=drain)
    assert processed == ids
    assert statuses(db_session) == ["completed", "completed"]


def test_drain_inside_handler_preserves_follow_up_jobs(db_session, monkeypatch):
    ids = queue(db_session, 1)
    factory = configure(db_session, monkeypatch)
    drain = worker.DrainRequest()

    def process(job_id):
        drain.request()
        with factory() as db:
            job = db.get(Job, job_id)
            job.status = "completed"
            db.add(Job(case_id=job.case_id, job_type=job.job_type, status="pending"))
            db.commit()

    monkeypatch.setattr(worker, "process_job", process)
    worker.run_worker(drain=drain)
    assert ids
    assert statuses(db_session) == ["completed", "pending"]


def test_handler_failure_during_drain_is_committed_before_exit(db_session, monkeypatch):
    queue(db_session)
    configure(db_session, monkeypatch)
    drain = worker.DrainRequest()

    def fail(job_id):
        drain.request()
        raise RuntimeError("processing failed during a requested drain")

    monkeypatch.setattr(worker, "process_job", fail)
    worker.run_worker(drain=drain)
    assert statuses(db_session) == ["failed", "pending"]


def test_drain_during_readiness_check_does_not_claim(db_session, monkeypatch):
    queue(db_session)
    configure(db_session, monkeypatch)
    drain = worker.DrainRequest()

    def recover(**kwargs):
        drain.request()
        return False

    monkeypatch.setattr(worker, "recover_after_model_ready", recover)
    worker.run_worker(drain=drain)
    assert statuses(db_session) == ["pending", "pending"]
