from contextlib import contextmanager

import httpx
import pytest

from services.search.model_startup import SetupStatus
from services.worker.app import main as worker


def response(status):
    return httpx.Response(200, json=status.model_dump(mode="json"),
                          request=httpx.Request("GET", "http://ai/setup"))


@pytest.mark.parametrize("state", ["downloading", "warming_up", "error", "disabled"])
def test_preparing_worker_does_not_queue_recovery_jobs(monkeypatch, state):
    monkeypatch.setattr(worker.httpx, "get", lambda *a, **k: response(SetupStatus(state=state)))
    monkeypatch.setattr(worker, "get_session_factory", lambda: pytest.fail("not ready"))
    assert worker.recover_after_model_ready() is False


def test_real_model_ready_queues_via_normal_worker_transaction(monkeypatch):
    calls = []

    class Session:
        def commit(self):
            calls.append("commit")

    @contextmanager
    def session():
        yield Session()

    def get(url, **kwargs):
        assert url.endswith("/setup")
        assert kwargs == {"timeout": 2, "follow_redirects": False, "trust_env": False}
        return response(SetupStatus(state="ready", ready=True))

    monkeypatch.setattr(worker.httpx, "get", get)
    monkeypatch.setattr(worker, "get_session_factory", lambda: session)
    monkeypatch.setattr(worker, "queue_startup_embeddings", lambda db: calls.append("queue") or 2)
    assert worker.recover_after_model_ready() is True
    assert calls == ["queue", "commit"]
    # Stable-ready polling doesn't repeatedly scan the vector store.
    assert worker.recover_after_model_ready(reconcile=False) is True
    assert calls == ["queue", "commit"]


def test_worker_readiness_outage_is_not_a_job_failure(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("secret internal URL")

    monkeypatch.setattr(worker.httpx, "get", unavailable)
    monkeypatch.setattr(worker, "get_session_factory", lambda: pytest.fail("unavailable"))
    assert worker.recover_after_model_ready() is False
