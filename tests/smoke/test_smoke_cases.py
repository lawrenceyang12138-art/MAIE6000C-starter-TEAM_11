from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_smoke_end_to_end_case_flow():
    base_url = os.getenv("SMOKE_BASE_URL")
    if not base_url:
        pytest.skip("SMOKE_BASE_URL not set")

    create_response = httpx.post(
        f"{base_url}/cases",
        json={
            "title": "Production outage alert",
            "description": "Several users report the service is down and requests are failing.",
        },
        timeout=10,
    )
    assert create_response.status_code == 201

    case_id = create_response.json()["case"]["id"]

    deadline = time.time() + 30
    last_payload = None

    while time.time() < deadline:
        poll = httpx.get(f"{base_url}/cases/{case_id}", timeout=10)
        assert poll.status_code == 200
        last_payload = poll.json()

        if last_payload["status"] == "triaged":
            break

        time.sleep(1)

    assert last_payload is not None
    assert last_payload["status"] == "triaged"
    assert last_payload["ai_label"] in {
        "access",
        "incident",
        "billing",
        "maintenance",
        "general",
    }
