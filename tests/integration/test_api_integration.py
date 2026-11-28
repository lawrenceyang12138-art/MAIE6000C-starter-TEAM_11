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


def test_an_unknown_mount_is_a_404_with_a_machine_readable_code(client):
    """Contract §6.2: unknown mount -> 404 unknown_mount; §6.1: coded envelope."""
    response = client.post(
        "/roots", json={"mount_id": "not-a-mount", "relative_path": "week5"}
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "unknown_mount"
    assert "not-a-mount" in detail["message"]


def test_a_path_escaping_the_mount_is_a_403_path_out_of_scope(client):
    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "../etc"}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_out_of_scope"
