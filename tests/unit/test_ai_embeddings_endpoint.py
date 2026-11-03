from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from services.ai.app import main as ai_main
from services.ai.app.main import app, get_local_embedding_backend
from services.search.embeddings import EmbeddingUnavailable
from services.search.model_startup import SetupStatus
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS as DIMENSIONS


@pytest.fixture(autouse=True)
def startup_without_real_model_or_download(monkeypatch):
    class FakeStartup:
        def __init__(self):
            self.status = SetupStatus(state="downloading", message="Downloading test model.")
            self.started = 0
            self.stopped = 0
            self.retried = 0

        def start(self):
            self.started += 1
            return self.snapshot()

        def shutdown(self):
            self.stopped += 1

        def snapshot(self):
            return self.status.model_dump(mode="json")

        def retry(self):
            self.retried += 1
            self.status = SetupStatus(state="checking_environment")
            return self.snapshot()

        def get_backend(self):
            raise EmbeddingUnavailable("ai_preparing")

    startup = FakeStartup()

    @lru_cache(maxsize=1)
    def fake_startup():
        return startup

    monkeypatch.setattr(ai_main, "get_model_startup", fake_startup)
    return startup


def test_ai_embedding_contract_and_validation():
    class Backend:
        model_id = MODEL_ID
        dimensions = DIMENSIONS

        def embed(self, texts, kind):
            assert kind == "query"
            return [[[1.0] + [0.0] * (DIMENSIONS - 1)] for _ in texts]

    app.dependency_overrides[get_local_embedding_backend] = Backend
    try:
        with TestClient(app) as client:
            response = client.post("/embeddings", json={"texts": ["hello"], "kind": "query"})
            assert response.status_code == 200
            assert response.json()["model"] == MODEL_ID
            assert len(response.json()["vectors"][0][0]) == DIMENSIONS
            assert response.json()["representation"] == "token_multivector"
            assert response.json()["scoring"] == "maxsim_mean"
            assert client.post("/embeddings", json={"texts": [" "]}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_ai_missing_model_returns_503():
    class Backend:
        def embed(self, texts, kind):
            raise EmbeddingUnavailable("local_model_missing")

    app.dependency_overrides[get_local_embedding_backend] = Backend
    try:
        with TestClient(app) as client:
            response = client.post("/embeddings", json={"texts": ["hello"]})
            assert response.status_code == 503
            assert response.json()["detail"] == "local_model_missing"
    finally:
        app.dependency_overrides.clear()


def test_ai_health_distinguishes_process_liveness_and_model_readiness(
    startup_without_real_model_or_download,
):
    startup = startup_without_real_model_or_download
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        status = client.get("/setup")
        assert status.status_code == 200
        assert status.json()["state"] == "downloading"
        assert status.json()["ready"] is False
        response = client.post("/embeddings", json={"texts": ["hello"]})
        assert response.status_code == 503
        assert response.json()["detail"] == "ai_preparing"
        startup.status = SetupStatus(state="ready", ready=True, progress=100)
        assert client.get("/health/ready").status_code == 200
    assert startup.started == 1
    assert startup.stopped == 1


def test_ai_setup_retry_returns_accepted_without_blocking_on_preparation(
    startup_without_real_model_or_download,
):
    startup = startup_without_real_model_or_download
    with TestClient(app) as client:
        response = client.post("/setup/retry")
        assert response.status_code == 202
        assert response.json()["state"] == "checking_environment"
        assert response.json()["ready"] is False
        assert startup.retried == 1
