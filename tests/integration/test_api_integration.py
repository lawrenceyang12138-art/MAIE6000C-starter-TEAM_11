def test_create_case_enqueues_job(client):
    response = client.post(
        "/cases",
        json={
            "title": "Cannot login",
            "description": "User cannot access the dashboard after password reset.",
        },
    )

    assert response.status_code == 201
    data = response.json()

    assert data["case"]["status"] == "queued"
    assert data["job"]["status"] == "pending"

    case_id = data["case"]["id"]
    get_case = client.get(f"/cases/{case_id}")

    assert get_case.status_code == 200
    assert get_case.json()["title"] == "Cannot login"


def test_health_ready(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
