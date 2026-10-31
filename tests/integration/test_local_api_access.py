"""Browser refusals must precede directory access and persistent writes."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from services.common.models import AuthorizedRoot, Job


@pytest.mark.parametrize("headers,code", [
    ({"host": "attacker.example"}, "invalid_host"),
    ({"host": "localhost.attacker.example"}, "invalid_host"),
    ({"host": "attacker@localhost"}, "invalid_host"),
    ({"host": "localhost:99999"}, "invalid_host"),
    ({"origin": "https://attacker.example"}, "origin_not_allowed"),
    ({"origin": "null"}, "origin_not_allowed"),
    ({"origin": "http://localhost:3000.attacker.example"}, "origin_not_allowed"),
    ({"sec-fetch-site": "cross-site"}, "origin_not_allowed"),
])
def test_untrusted_browser_cannot_read_mounts_or_create_roots(client, db_session, headers, code):
    for method, path in (("GET", "/mounts"), ("POST", "/roots")):
        response = client.request(
            method, path, headers=headers,
            **({"json": {"mount_id": "corpus", "relative_path": "."}} if method == "POST" else {}),
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == code
    assert db_session.scalar(select(func.count()).select_from(AuthorizedRoot)) == 0
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize("origin", [None, "http://testserver", "http://127.0.0.1:3000"])
def test_local_browser_and_cli_keep_normal_access(client, origin):
    headers = {"origin": origin} if origin else {}
    assert client.get("/mounts", headers=headers).status_code == 200
    response = client.post("/cases", json={"title": "Local case", "description": "Local input"},
                           headers=headers)
    assert response.status_code == 201


@pytest.mark.parametrize("content_type", [
    "application/x-www-form-urlencoded", "multipart/form-data; boundary=demo", "text/plain",
])
def test_simple_browser_form_cannot_trigger_a_state_change(client, db_session, content_type):
    response = client.post("/roots", content='{"mount_id":"corpus","relative_path":"."}',
                           headers={"content-type": content_type})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "origin_not_allowed"
    assert db_session.scalar(select(func.count()).select_from(Job)) == 0
