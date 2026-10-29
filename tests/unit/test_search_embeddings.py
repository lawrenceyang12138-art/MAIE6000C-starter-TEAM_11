from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from services.common.schemas import EmbeddingRequest
from services.search.embeddings import (
    EmbeddingUnavailable,
    HTTPEmbeddingBackend,
    LocalE5EmbeddingBackend,
    validate_vectors,
)
from services.search.text import DIMENSIONS, MODEL_FILES, MODEL_ID, MODEL_REVISION, tokenize


def test_chinese_tokens_do_not_cross_punctuation():
    assert tokenize("\u6570\u636e\u5e93\uff0c\u5907\u4efd") == (
        "\u6570\u636e",
        "\u636e\u5e93",
        "\u5907\u4efd",
    )
    assert tokenize("PASSWORD reset") == ("password", "reset")


@pytest.mark.parametrize("texts", [[], [" "], ["a" * 2001], ["x"] * 17])
def test_embedding_request_limits(texts):
    with pytest.raises(ValueError):
        EmbeddingRequest(texts=texts)


@pytest.mark.parametrize(
    "vectors", [[], [[0.0] * DIMENSIONS], [[1.0]], [[float("nan")] * DIMENSIONS]]
)
def test_invalid_vectors_are_rejected(vectors):
    with pytest.raises(EmbeddingUnavailable, match="invalid_embedding_response"):
        validate_vectors(vectors, 1)


def test_missing_local_model_cannot_trigger_download(tmp_path):
    with pytest.raises(EmbeddingUnavailable, match="local_model_missing"):
        LocalE5EmbeddingBackend(str(tmp_path)).embed(["hello"])


def test_malformed_model_manifest_returns_safe_unavailable(tmp_path):
    manifest = {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": list(MODEL_FILES)}
    (tmp_path / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(EmbeddingUnavailable, match="^local_model_unusable$"):
        LocalE5EmbeddingBackend(str(tmp_path)).embed(["hello"])


def test_self_signed_manifest_cannot_claim_the_pinned_model_revision(tmp_path, monkeypatch):
    checksums = {}
    for filename in MODEL_FILES:
        content = f"replacement artifact: {filename}".encode()
        (tmp_path / filename).write_bytes(content)
        checksums[filename] = hashlib.sha256(content).hexdigest()
    manifest = {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": checksums}
    (tmp_path / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    class UnexpectedLoader:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            pytest.fail("untrusted replacement model reached the inference loader")

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModel=UnexpectedLoader, AutoTokenizer=UnexpectedLoader),
    )
    with pytest.raises(EmbeddingUnavailable, match="^local_model_unusable$"):
        LocalE5EmbeddingBackend(str(tmp_path)).embed(["hello"])


def test_http_timeout_has_safe_reason(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        raise httpx.ReadTimeout("sensitive path and response body")

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(EmbeddingUnavailable, match="^ai_timeout$"):
        HTTPEmbeddingBackend("http://ai:8100").embed(["test"], "query")


def test_http_model_version_mismatch(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "model": MODEL_ID + "wrong",
            "dimensions": DIMENSIONS,
            "vectors": [[1.0] + [0.0] * (DIMENSIONS - 1)],
        },
        request=httpx.Request("POST", "http://ai/embeddings"),
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    with pytest.raises(EmbeddingUnavailable, match="embedding_model_mismatch"):
        HTTPEmbeddingBackend("http://ai").embed(["hello"])
