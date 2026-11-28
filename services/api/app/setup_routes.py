"""Read safe local-AI preparation progress without blocking the rest of the API."""

import httpx
from fastapi import APIRouter, Depends
from pydantic import ValidationError

from services.common.config import Settings, get_settings
from services.search.model_startup import MESSAGES, SetupStatus

router = APIRouter()


def _proxy(settings: Settings, retry: bool = False) -> SetupStatus:
    if not settings.embedding_enabled:
        return SetupStatus(state="disabled", message=MESSAGES["disabled"])
    try:
        # The URL is operator config, never browser input. Don't follow redirects
        # or leak an upstream response/exception into the public progress panel.
        response = httpx.request(
            "POST" if retry else "GET",
            settings.ai_service_url.rstrip("/") + ("/setup/retry" if retry else "/setup"),
            timeout=2.0, follow_redirects=False, trust_env=False,
        )
        response.raise_for_status()
        status = SetupStatus.model_validate(response.json())
        if status.ready != (status.state == "ready"):
            raise ValueError("inconsistent model readiness")
        # Only locally curated safe text is displayed; upstream strings aren't trusted.
        status.message = MESSAGES.get(status.state, "Preparing the local AI environment.")
        return status
    except (httpx.HTTPError, ValidationError, ValueError):
        return SetupStatus(state="unavailable", message=MESSAGES["unavailable"],
                           error_code="ai_unavailable", retryable=True)


@router.get("/setup", response_model=SetupStatus)
def setup_status(settings: Settings = Depends(get_settings)) -> SetupStatus:
    return _proxy(settings)


@router.post("/setup/retry", response_model=SetupStatus, status_code=202)
def retry_setup(settings: Settings = Depends(get_settings)) -> SetupStatus:
    return _proxy(settings, retry=True)
