"""The browser sees model readiness, not process health or upstream secrets."""

from datetime import datetime, timezone

import httpx
import pytest

from services.api.app import setup_routes
from services.common.config import get_settings
from services.search.model_startup import SetupStatus


def upstream(payload, code=200):
    return httpx.Response(code, json=payload, request=httpx.Request("GET", "http://ai/setup"))


def test_setup_status_uses_bounded_local_proxy_and_safe_text(client, monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return upstream(SetupStatus(
            state="downloading", stage_progress=25, downloaded_bytes=100, total_bytes=400,
            message="untrusted server path C:/private/secrets",
        ).model_dump(mode="json"))

    monkeypatch.setattr(setup_routes.httpx, "request", request)
    response = client.get("/setup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "downloading" and payload["ready"] is False
    assert payload["stage_progress"] == 25 and payload["downloaded_bytes"] == 100
    assert "private" not in response.text
    assert calls[0][0] == "GET" and calls[0][1].endswith("/setup")
    assert calls[0][2] == {"timeout": 2.0, "follow_redirects": False, "trust_env": False}


def test_setup_retry_is_an_explicit_post_and_returns_accepted(client, monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        return upstream(SetupStatus(state="checking_model").model_dump(mode="json"), 202)

    monkeypatch.setattr(setup_routes.httpx, "request", request)
    response = client.post("/setup/retry")
    assert response.status_code == 202
    assert response.json()["state"] == "checking_model"
    assert calls[0][0] == "POST" and calls[0][1].endswith("/setup/retry")


@pytest.mark.parametrize("path", ["/setup", "/setup/retry"])
def test_disabled_setup_never_contacts_ai(client, monkeypatch, path):
    monkeypatch.setattr(get_settings(), "embedding_enabled", False)
    monkeypatch.setattr(setup_routes.httpx, "request", lambda *a, **k: pytest.fail("AI disabled"))
    response = client.get(path) if path == "/setup" else client.post(path)
    assert response.json()["state"] == "disabled"
    assert response.json()["ready"] is False
    assert response.json()["retryable"] is False


@pytest.mark.parametrize("failure", ["timeout", "503", "invalid", "wrong_model", "fake_ready"])
def test_unavailable_ai_cannot_fake_ready_or_leak_details(client, monkeypatch, failure):
    def request(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("proxy token and sensitive path")
        if failure == "503":
            return upstream({"detail": "sensitive stacktrace"}, 503)
        payload = SetupStatus(state="ready", ready=True).model_dump(mode="json")
        if failure == "invalid":
            payload["error_code"] = "sensitive path C:/secret"
        elif failure == "wrong_model":
            payload["model"] = "other-revision"
        elif failure == "fake_ready":
            payload["ready"] = False
        return upstream(payload)

    monkeypatch.setattr(setup_routes.httpx, "request", request)
    response = client.get("/setup")
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"
    assert response.json()["ready"] is False
    assert response.json()["error_code"] == "ai_unavailable"
    assert "sensitive" not in response.text and "secret" not in response.text
    datetime.fromisoformat(response.json()["updated_at"].replace("Z", "+00:00")).astimezone(
        timezone.utc,
    )
