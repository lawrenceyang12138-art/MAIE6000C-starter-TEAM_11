from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from threading import Lock
from typing import Literal, Protocol

import httpx
from pydantic import ValidationError

from services.common.schemas import EmbeddingResponse
from services.search.text import (
    DIMENSIONS,
    MAX_BATCH_SIZE,
    MAX_TEXT_CHARS,
    MODEL_ID,
    MODEL_FILES,
    MODEL_REVISION,
    PINNED_MODEL_SHA256,
)

EmbeddingKind = Literal["query", "passage"]


class EmbeddingUnavailable(RuntimeError):
    """A safe, public reason code; never includes paths or remote response bodies."""


class EmbeddingBackend(Protocol):
    model_id: str
    dimensions: int

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[list[float]]: ...


def validate_vectors(vectors: list[list[float]], count: int) -> list[list[float]]:
    if len(vectors) != count:
        raise EmbeddingUnavailable("invalid_embedding_response")
    for vector in vectors:
        if len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector):
            raise EmbeddingUnavailable("invalid_embedding_response")
        norm = math.sqrt(sum(value * value for value in vector))
        if not 0.99 <= norm <= 1.01:
            raise EmbeddingUnavailable("invalid_embedding_response")
    return vectors


class HTTPEmbeddingBackend:
    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url.rstrip("/") + "/embeddings"
        self.timeout = timeout

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[list[float]]:
        try:
            response = httpx.post(
                self.url,
                json={"texts": texts, "kind": kind},
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            payload = EmbeddingResponse.model_validate(response.json())
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailable("ai_timeout") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable("ai_unavailable") from exc
        except (ValidationError, ValueError) as exc:
            raise EmbeddingUnavailable("invalid_embedding_response") from exc
        if payload.model != MODEL_ID or payload.dimensions != DIMENSIONS:
            raise EmbeddingUnavailable("embedding_model_mismatch")
        return validate_vectors(payload.vectors, len(texts))


class LocalE5EmbeddingBackend:
    """Pinned multilingual E5, loaded only from an explicitly prepared local directory."""

    model_id = MODEL_ID
    dimensions = DIMENSIONS

    def __init__(self, model_path: str, cpu_threads: int = 4):
        self.model_path = Path(model_path)
        self.cpu_threads = cpu_threads
        self._model = None
        self._tokenizer = None
        self._lock = Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        manifest_path = self.model_path / "model-manifest.json"
        if not manifest_path.is_file():
            raise EmbeddingUnavailable("local_model_missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["revision"] != MODEL_REVISION or manifest["model"] != MODEL_ID:
                raise ValueError("model revision mismatch")
            checksums = manifest["sha256"]
            if not isinstance(checksums, dict) or set(checksums) != set(MODEL_FILES):
                raise ValueError("model manifest is incomplete")
            if checksums != PINNED_MODEL_SHA256:
                raise ValueError("model manifest does not match the pinned revision")
            for filename, expected in checksums.items():
                target = (self.model_path / filename).resolve()
                if not target.is_relative_to(self.model_path.resolve()):
                    raise ValueError("invalid model file")
                with target.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise ValueError("model file checksum mismatch")
            import torch

            # This service uses PyTorch. Avoid importing unrelated installed TF packages.
            os.environ.setdefault("USE_TF", "0")
            from transformers import AutoModel, AutoTokenizer

            torch.set_num_threads(self.cpu_threads)
            tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_path),
                local_files_only=True,
                trust_remote_code=False,
            )
            model = AutoModel.from_pretrained(
                str(self.model_path),
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
            ).eval()
            if model.config.hidden_size != DIMENSIONS:
                raise ValueError("model dimensions mismatch")
            self._tokenizer = tokenizer
            self._model = model
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            raise EmbeddingUnavailable("local_model_unusable") from exc

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[list[float]]:
        if not 1 <= len(texts) <= MAX_BATCH_SIZE:
            raise ValueError(f"batch size must be between 1 and {MAX_BATCH_SIZE}")
        if kind not in ("query", "passage"):
            raise ValueError("embedding kind must be query or passage")
        if any(not text.strip() or len(text) > MAX_TEXT_CHARS for text in texts):
            raise ValueError(f"each text must contain 1 to {MAX_TEXT_CHARS} characters")
        with self._lock:
            self._load()
            import torch
            import torch.nn.functional as functional

            try:
                inputs = self._tokenizer(
                    [f"{kind}: {text}" for text in texts],
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                with torch.inference_mode():
                    output = self._model(**inputs).last_hidden_state
                    mask = inputs["attention_mask"].unsqueeze(-1).bool()
                    pooled = output.masked_fill(~mask, 0.0).sum(dim=1) / mask.sum(dim=1)
                    vectors = functional.normalize(pooled, p=2, dim=1).tolist()
            except (RuntimeError, ValueError) as exc:
                raise EmbeddingUnavailable("local_inference_failed") from exc
        return validate_vectors(vectors, len(texts))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return max(-1.0, min(1.0, dot / norm)) if norm else 0.0
