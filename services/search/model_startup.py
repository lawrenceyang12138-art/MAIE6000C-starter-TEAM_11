"""Non-blocking startup state: verified bytes and real inference, not liveness."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Callable, Literal, get_args

from pydantic import BaseModel, Field

from services.common.config import Settings
from services.search.embeddings import (
    EmbeddingUnavailable, LocalPplxEmbeddingBackend, validate_vectors,
)
from services.search.model_preparation import PreparationError, prepare_local_model
from services.search.text import MODEL_FILES, MODEL_ID

logger = logging.getLogger(__name__)

SetupState = Literal[
    "pending", "checking_environment", "installing_dependencies", "checking_model",
    "downloading", "verifying", "loading", "warming_up", "ready", "error", "disabled",
    "unavailable",
]
SetupError = Literal[
    "ai_disabled", "ai_unavailable", "embedding_dependencies_missing",
    "embedding_dependencies_incompatible", "model_configuration_invalid",
    "model_path_outside_storage", "model_download_failed", "model_download_invalid_range",
    "model_download_size_mismatch", "model_checksum_mismatch", "model_storage_unwritable",
    "model_storage_error", "local_model_missing_or_corrupt", "preparation_cancelled",
    "local_model_unusable", "local_model_missing", "local_inference_failed",
    "invalid_embedding_response", "model_preparation_failed",
]

MESSAGES = {
    "pending": "Local AI preparation is pending. Keyword search remains available.",
    "checking_environment": "Checking the installed local inference environment.",
    "checking_model": "Checking the pinned local model files.",
    "downloading": "Downloading the pinned model. Keyword search remains available.",
    "verifying": "Verifying all model files against the pinned SHA-256 hashes.",
    "loading": "Loading the verified model on the local CPU.",
    "warming_up": "Running local query and document inference to warm up the model.",
    "ready": "Local AI is ready. Model integrity and warm-up checks passed.",
    "disabled": "Local AI is disabled. Keyword search remains available.",
    "unavailable": "Local AI service is unavailable. Keyword search remains available.",
    "error": "Local AI preparation failed. Keyword search remains available; retry setup.",
}


class SetupStatus(BaseModel):
    state: SetupState = "pending"
    ready: bool = False
    stage_progress: float | None = Field(default=None, ge=0, le=100)
    # Overall time cannot be predicted from download size; don't invent a percentage.
    progress: float | None = Field(default=None, ge=0, le=100)
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    completed_files: int = Field(default=0, ge=0)
    total_files: int = Field(default=len(MODEL_FILES), ge=0)
    model: Literal[MODEL_ID] = MODEL_ID
    message: str = MESSAGES["pending"]
    error_code: SetupError | None = None
    retryable: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def check_embedding_environment() -> None:
    """Dependencies are automatically installed by the launcher/image build.

    Never run pip into a live server or execute the model's requirements file.
    A direct bare uvicorn launch reports a missing environment explicitly.
    """
    required = {
        "torch": "2.8.0", "transformers": "5.22.0", "sentence-transformers": "6.2.0",
    }
    try:
        for package, version in required.items():
            installed = metadata.version(package).split("+", 1)[0]
            if installed != version:
                raise PreparationError("embedding_dependencies_incompatible")
        metadata.version("huggingface-hub")
    except metadata.PackageNotFoundError as exc:
        raise PreparationError("embedding_dependencies_missing") from exc


class ModelStartup:
    def __init__(
        self,
        settings: Settings,
        *,
        backend_factory: Callable | None = None,
        preparer: Callable = prepare_local_model,
        environment_check: Callable = check_embedding_environment,
    ):
        self.settings = settings
        self._factory = backend_factory or (
            lambda: LocalPplxEmbeddingBackend(
                settings.embedding_model_path, settings.embedding_cpu_threads,
            )
        )
        self._prepare = preparer
        self._environment = environment_check
        self._lock = Lock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._backend = None
        self._status = SetupStatus()

    def snapshot(self) -> dict:
        with self._lock:
            return self._status.model_dump(mode="json")

    def _update(self, **values) -> None:
        with self._lock:
            if "state" in values:
                values.setdefault("message", MESSAGES[values["state"]])
                values.setdefault("stage_progress", None)
            values["updated_at"] = datetime.now(timezone.utc)
            self._status = SetupStatus.model_validate({**self._status.model_dump(), **values})

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self._status.model_dump(mode="json")
            if self._status.ready:
                return self._status.model_dump(mode="json")
            if not self.settings.embedding_enabled:
                self._status = SetupStatus(state="disabled", message=MESSAGES["disabled"])
                return self._status.model_dump(mode="json")
            self._cancel.clear()
            self._backend = None
            self._status = SetupStatus(
                state="checking_environment", message=MESSAGES["checking_environment"],
            )
            self._thread = Thread(target=self._run, name="local-model-setup", daemon=True)
            self._thread.start()
            return self._status.model_dump(mode="json")

    def retry(self) -> dict:
        return self.start()  # Single flight, including concurrent POSTs.

    def _run(self) -> None:
        try:
            self._environment()
            self._prepare(
                Path(self.settings.embedding_model_path), progress=self._update,
                cancel=self._cancel, allow_download=self.settings.embedding_auto_prepare,
                timeout=self.settings.embedding_download_timeout_seconds,
                retries=self.settings.embedding_download_retries,
            )
            if self._cancel.is_set():
                return
            self._update(state="loading")
            backend = self._factory()
            backend.load()
            if self._cancel.is_set():
                return
            self._update(state="warming_up")
            # Exercise both native paths, their masks and the vector wire contract.
            validate_vectors(backend.embed(["Local search warm-up query."], "query"), 1)
            validate_vectors(backend.embed(
                ["A local document passage for model warm-up."], "passage",
            ), 1)
            with self._lock:
                if self._cancel.is_set():
                    return
                self._backend = backend
                self._status = self._status.model_copy(update={
                    "state": "ready", "ready": True, "stage_progress": 100.0,
                    "progress": 100.0, "retryable": False, "error_code": None,
                    "message": MESSAGES["ready"], "updated_at": datetime.now(timezone.utc),
                })
            logger.info("local_model_ready", extra={"model": MODEL_ID})
        except (PreparationError, EmbeddingUnavailable) as exc:
            code = str(exc) if str(exc) in get_args(SetupError) else "model_preparation_failed"
            self._update(state="error", error_code=code, retryable=True, ready=False)
            logger.warning("local_model_setup_failed", extra={"reason_code": code})
        except Exception:
            # No exception bodies, proxy URLs, host paths or credentials in public status.
            self._update(state="error", error_code="model_preparation_failed",
                         retryable=True, ready=False)
            logger.warning("local_model_setup_failed", extra={"reason_code": "internal_error"})

    def get_backend(self):
        with self._lock:
            if self._status.ready and self._backend is not None:
                return self._backend
            code = self._status.error_code
            if self._status.state == "disabled":
                code = "ai_disabled"
        raise EmbeddingUnavailable(code or "ai_preparing")

    def shutdown(self, timeout: float = 5) -> None:
        self._cancel.set()
        thread = self._thread
        if thread and thread is not current_thread():
            thread.join(timeout)
        self._update(state="pending", ready=False, progress=None, retryable=False,
                     error_code=None, message="Local AI preparation stopped.")
