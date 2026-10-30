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

from services.search.schemas import TokenEmbeddingResponse
from services.search.text import (
    MAX_BATCH_SIZE,
    MAX_DOCUMENT_MODEL_TOKENS,
    MAX_TEXT_CHARS,
    MODEL_FILES,
    MODEL_FORWARD_BATCH_SIZE,
    MODEL_ID,
    MODEL_REVISION,
    PINNED_MODEL_SHA256,
    TOKEN_DIMENSIONS,
)

EmbeddingKind = Literal["query", "passage"]
TokenVectors = list[list[float]]


class EmbeddingUnavailable(RuntimeError):
    """A safe public reason code, never an exception body or a filesystem path."""


class EmbeddingBackend(Protocol):
    model_id: str
    dimensions: int

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[TokenVectors]: ...


def validate_vectors(vectors: list[TokenVectors], count: int) -> list[TokenVectors]:
    """Validate a ragged batch of normalized token vectors; dense output is invalid."""
    try:
        if len(vectors) != count:
            raise ValueError("batch count")
        for matrix in vectors:
            if not isinstance(matrix, list) or not 1 <= len(matrix) <= MAX_DOCUMENT_MODEL_TOKENS:
                raise ValueError("token count")
            for token in matrix:
                if not isinstance(token, list) or len(token) != TOKEN_DIMENSIONS:
                    raise ValueError("token dimensions")
                if not all(isinstance(value, (int, float)) and math.isfinite(value)
                           for value in token):
                    raise ValueError("non-finite token")
                norm = math.sqrt(sum(value * value for value in token))
                if not 0.99 <= norm <= 1.01:
                    raise ValueError("token norm")
    except (TypeError, ValueError, OverflowError) as exc:
        raise EmbeddingUnavailable("invalid_embedding_response") from exc
    return vectors


class HTTPEmbeddingBackend:
    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url.rstrip("/") + "/embeddings"
        self.timeout = timeout

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[TokenVectors]:
        try:
            response = httpx.post(
                self.url,
                json={"texts": texts, "kind": kind},
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            payload = TokenEmbeddingResponse.model_validate(response.json())
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailable("ai_timeout") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable("ai_unavailable") from exc
        except (ValidationError, ValueError) as exc:
            raise EmbeddingUnavailable("invalid_embedding_response") from exc
        if payload.model != MODEL_ID or payload.dimensions != TOKEN_DIMENSIONS:
            raise EmbeddingUnavailable("embedding_model_mismatch")
        return validate_vectors(payload.vectors, len(texts))


class LocalPplxEmbeddingBackend:
    """Pinned offline ColBERT encoder with native Q/D markers and token masking."""

    model_id = MODEL_ID
    dimensions = TOKEN_DIMENSIONS

    def __init__(self, model_path: str, cpu_threads: int = 4):
        self.model_path = Path(model_path)
        self.cpu_threads = cpu_threads
        self._model = None
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
            if (not isinstance(checksums, dict) or set(checksums) != set(MODEL_FILES)
                    or checksums != PINNED_MODEL_SHA256):
                raise ValueError("model manifest does not match the pinned revision")
            for filename, expected in checksums.items():
                target = (self.model_path / filename).resolve()
                if not target.is_relative_to(self.model_path.resolve()):
                    raise ValueError("invalid model file")
                with target.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise ValueError("model file checksum mismatch")
            os.environ.setdefault("USE_TF", "0")
            import torch
            from sentence_transformers import MultiVectorEncoder

            torch.set_num_threads(self.cpu_threads)
            self._model = MultiVectorEncoder(
                str(self.model_path), device="cpu", local_files_only=True,
                trust_remote_code=False, model_kwargs={"dtype": torch.float32},
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError,
                AttributeError) as exc:
            raise EmbeddingUnavailable("local_model_unusable") from exc

    def embed(self, texts: list[str], kind: EmbeddingKind = "passage") -> list[TokenVectors]:
        if not 1 <= len(texts) <= MAX_BATCH_SIZE:
            raise ValueError(f"batch size must be between 1 and {MAX_BATCH_SIZE}")
        if kind not in ("query", "passage"):
            raise ValueError("embedding kind must be query or passage")
        if any(not text.strip() or len(text) > MAX_TEXT_CHARS for text in texts):
            raise ValueError(f"each text must contain 1 to {MAX_TEXT_CHARS} characters")
        with self._lock:
            self._load()
            try:
                encode = (self._model.encode_query if kind == "query"
                          else self._model.encode_document)
                matrices = encode(texts, batch_size=min(MODEL_FORWARD_BATCH_SIZE, len(texts)),
                                  show_progress_bar=False,
                                  convert_to_numpy=True)
                vectors = [matrix.tolist() for matrix in matrices]
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                raise EmbeddingUnavailable("local_inference_failed") from exc
        return validate_vectors(vectors, len(texts))


def late_interaction_score(query: TokenVectors, document: TokenVectors) -> float:
    """Mean per-query-token maximum cosine, preserving native MaxSim ranking.

    Division by the query token count fits the public 0..1 hybrid contract.
    Query and document token vectors are never pooled into a dense embedding.
    """
    if not query or not document:
        return 0.0
    import numpy as np

    similarities = np.asarray(query, dtype=np.float32) @ np.asarray(document, dtype=np.float32).T
    return max(0.0, min(1.0, float(similarities.max(axis=1).mean())))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Numeric utility; the active search path uses token MaxSim instead."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return max(-1.0, min(1.0, dot / norm)) if norm else 0.0
