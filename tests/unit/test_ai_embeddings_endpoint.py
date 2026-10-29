from fastapi.testclient import TestClient

from services.ai.app.main import app, get_local_embedding_backend
from services.search.embeddings import EmbeddingUnavailable
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS as DIMENSIONS


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
