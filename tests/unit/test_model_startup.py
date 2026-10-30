"""Startup readiness means verified files and both warm-up inference paths passed."""

from __future__ import annotations

from threading import Event, Thread

import pytest

from services.common.config import Settings
from services.search.embeddings import EmbeddingUnavailable
from services.search.model_preparation import PreparationError
from services.search.model_startup import ModelStartup


class Backend:
    def __init__(self):
        self.calls = []

    def load(self):
        self.calls.append("load")

    def embed(self, texts, kind):
        self.calls.append((texts, kind))
        return [[[1.0] + [0.0] * 127]]


def options(tmp_path, **kwargs):
    return Settings(_env_file=None, embedding_model_path=str(tmp_path / "model"), **kwargs)


def finish(startup):
    thread = startup._thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive(), "synthetic startup must terminate without real model/network work"
    return startup.snapshot()


def test_ready_only_after_environment_prepare_load_and_both_native_warmups(tmp_path):
    calls = []
    backend = Backend()

    def preparer(path, **kwargs):
        assert path == tmp_path / "model"
        assert kwargs["allow_download"] is True
        assert kwargs["timeout"] == 30
        assert kwargs["retries"] == 3
        assert not kwargs["cancel"].is_set()
        calls.append("prepare")
        kwargs["progress"](state="downloading", downloaded_bytes=8, total_bytes=16)

    startup = ModelStartup(
        options(tmp_path),
        environment_check=lambda: calls.append("environment"),
        preparer=preparer,
        backend_factory=lambda: backend,
    )
    assert startup.snapshot()["state"] == "pending"
    with pytest.raises(EmbeddingUnavailable, match="^ai_preparing$"):
        startup.get_backend()
    startup.start()
    status = finish(startup)
    assert calls == ["environment", "prepare"]
    assert backend.calls[0] == "load"
    assert [kind for _, kind in backend.calls[1:]] == ["query", "passage"]
    assert status["state"] == "ready"
    assert status["ready"] is True
    assert status["progress"] == 100
    assert status["stage_progress"] == 100
    assert status["retryable"] is False
    assert status["error_code"] is None
    assert status["updated_at"].endswith("Z")
    assert startup.get_backend() is backend
    startup.start()
    startup.retry()
    assert calls == ["environment", "prepare"], "ready restarts must reuse process model"
    startup.shutdown()


def test_disabled_ai_never_checks_installs_downloads_or_constructs_backend(tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled AI must perform no setup work")

    startup = ModelStartup(
        options(tmp_path, embedding_enabled=False),
        environment_check=forbidden,
        preparer=forbidden,
        backend_factory=forbidden,
    )
    status = startup.start()
    assert status["state"] == "disabled"
    assert status["ready"] is False
    assert startup._thread is None
    assert startup.retry()["state"] == "disabled"
    with pytest.raises(EmbeddingUnavailable, match="^ai_disabled$"):
        startup.get_backend()


def test_preparation_progress_stays_responsive_and_does_not_claim_ready(tmp_path):
    entered = Event()
    release = Event()

    def preparer(path, **kwargs):
        kwargs["progress"](state="downloading", downloaded_bytes=12, total_bytes=40,
                           stage_progress=30, completed_files=1, total_files=3)
        entered.set()
        assert release.wait(5)

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    try:
        assert entered.wait(3)
        status = startup.snapshot()
        assert status["state"] == "downloading"
        assert status["ready"] is False
        assert status["progress"] is None, "unknown overall time is not a fake percent"
        assert status["stage_progress"] == 30
        assert status["downloaded_bytes"] == 12
        with pytest.raises(EmbeddingUnavailable, match="^ai_preparing$"):
            startup.get_backend()
    finally:
        release.set()
        finish(startup)
        startup.shutdown()


def test_concurrent_start_and_retry_are_single_flight(tmp_path):
    entered = Event()
    release = Event()
    calls = []

    def preparer(path, **kwargs):
        calls.append(path)
        entered.set()
        assert release.wait(5)

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    try:
        assert entered.wait(3)
        clients = [Thread(target=startup.retry) for _ in range(12)]
        for thread in clients:
            thread.start()
        for thread in clients:
            thread.join(2)
            assert not thread.is_alive()
        assert len(calls) == 1
    finally:
        release.set()
        finish(startup)
        startup.shutdown()


def test_failed_setup_has_safe_error_and_explicit_retry_can_recover(tmp_path):
    attempts = []

    def preparer(path, **kwargs):
        attempts.append(path)
        if len(attempts) == 1:
            raise PreparationError("model_download_failed")

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    status = finish(startup)
    assert status["state"] == "error"
    assert status["ready"] is False
    assert status["retryable"] is True
    assert status["error_code"] == "model_download_failed"
    with pytest.raises(EmbeddingUnavailable, match="^model_download_failed$"):
        startup.get_backend()
    startup.retry()
    assert finish(startup)["ready"] is True
    assert len(attempts) == 2
    startup.shutdown()


@pytest.mark.parametrize("failure_stage", ["environment", "load", "query", "passage"])
def test_each_required_stage_failure_prevents_ready(tmp_path, failure_stage):
    def environment():
        if failure_stage == "environment":
            raise PreparationError("embedding_dependencies_missing")

    class FailingBackend(Backend):
        def load(self):
            if failure_stage == "load":
                raise EmbeddingUnavailable("local_model_unusable")

        def embed(self, texts, kind):
            if failure_stage == kind:
                raise EmbeddingUnavailable("local_inference_failed")
            return super().embed(texts, kind)

    startup = ModelStartup(
        options(tmp_path), environment_check=environment, preparer=lambda *a, **k: None,
        backend_factory=FailingBackend,
    )
    startup.start()
    assert finish(startup)["state"] == "error"
    assert startup.snapshot()["ready"] is False
    with pytest.raises(EmbeddingUnavailable):
        startup.get_backend()
    startup.shutdown()


def test_unexpected_exception_never_leaks_credentials_or_paths(tmp_path):
    def preparer(*args, **kwargs):
        raise RuntimeError("https://user:secret@private-proxy.invalid C:/private/user/file")

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    status = finish(startup)
    assert status["error_code"] == "model_preparation_failed"
    assert "secret" not in str(status)
    assert "private" not in str(status)
    startup.shutdown()


@pytest.mark.parametrize("error_type", [PreparationError, EmbeddingUnavailable])
def test_unrecognized_reason_code_cannot_leave_setup_stuck_or_leak_text(tmp_path, error_type):
    def preparer(*args, **kwargs):
        raise error_type("unrecognized future error with secret token")

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    status = finish(startup)
    assert status["state"] == "error"
    assert status["error_code"] == "model_preparation_failed"
    assert status["retryable"] is True
    assert "secret" not in str(status)
    startup.shutdown()


def test_offline_mode_still_validates_loads_and_warms_existing_model(tmp_path):
    def preparer(path, **kwargs):
        assert kwargs["allow_download"] is False

    startup = ModelStartup(
        options(tmp_path, embedding_auto_prepare=False), environment_check=lambda: None,
        preparer=preparer, backend_factory=Backend,
    )
    startup.start()
    assert finish(startup)["ready"] is True
    startup.shutdown()


def test_shutdown_during_setup_cannot_publish_a_late_ready_backend(tmp_path):
    entered = Event()
    release = Event()

    def preparer(path, **kwargs):
        entered.set()
        assert release.wait(5)

    startup = ModelStartup(
        options(tmp_path), environment_check=lambda: None, preparer=preparer,
        backend_factory=Backend,
    )
    startup.start()
    assert entered.wait(3)
    startup.shutdown(timeout=0.01)
    release.set()
    assert finish(startup)["ready"] is False
    with pytest.raises(EmbeddingUnavailable):
        startup.get_backend()
