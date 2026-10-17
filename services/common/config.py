from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pythonjsonlogger import jsonlogger

from services.search.text import DIMENSIONS, MODEL_ID


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/maie6000c"
    ai_service_url: str = "http://ai:8100"
    worker_poll_seconds: float = 2.0
    worker_request_timeout_seconds: float = 20.0
    # Server-side allowlist of read-only source mounts: mount_id -> container path.
    # The UI may only select folders beneath these mounts; an unknown mount_id is
    # rejected. Spec: week04 docs/architecture.md "Folder access and local
    # deployment boundary" (adding a mount requires config change + restart).
    source_mounts: dict[str, str] = {"corpus": "/source/corpus"}
    embedding_enabled: bool = True
    embedding_model: Literal[MODEL_ID] = MODEL_ID
    embedding_dimensions: Literal[DIMENSIONS] = DIMENSIONS
    embedding_model_path: str = "models/multilingual-e5-small"
    embedding_cpu_threads: int = Field(default=4, ge=1, le=32)
    search_request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    search_keyword_weight: float = Field(default=0.65, gt=0, le=1)
    search_semantic_weight: float = Field(default=0.35, gt=0, le=1)
    search_max_candidates: int = Field(default=200, ge=50, le=2000)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class ServiceJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)
        if "service" not in log_record:
            parts = record.name.split(".")
            log_record["service"] = parts[1] if len(parts) > 1 and parts[0] == "services" else "app"


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(
        ServiceJsonFormatter("%(asctime)s %(levelname)s %(service)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    configure_logging._configured = True  # type: ignore[attr-defined]
