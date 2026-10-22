"""Integration tests for the W7 mount, root and job routes.

These routes are the contract surface the browser actually calls, so the tests
are written against the shapes D validates rather than against our models:
flat `{root_id, job_id, status}` on accept, `root_id`/`file_counts` on read,
`job_id`/`error_code` on jobs, and `claimed` surfaced as `running`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from services.api.app import main as api_main
from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
)


class _Settings:
    def __init__(self, source_mounts: dict[str, str]) -> None:
        self.source_mounts = source_mounts


@pytest.fixture()
def mount(tmp_path, monkeypatch):
    """A real directory served as the allowlisted `corpus` mount."""
    base = tmp_path / "corpus"
    (base / "regression").mkdir(parents=True)
    (base / "abnormal").mkdir()
    (base / ".hidden").mkdir()
    (base / "notes.txt").write_text("notes")
    monkeypatch.setattr(
        api_main, "get_settings", lambda: _Settings({"corpus": str(base)})
    )
    return base


def _create_root(client, relative_path: str = ".") -> dict:
    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": relative_path}
    )
    assert response.status_code == 202
    return response.json()


def _make_job(db: Session, **kwargs) -> int:
    job = Job(
        job_type=kwargs.pop("job_type", RootJobType.SCAN_ROOT.value),
        status=kwargs.pop("status", JobStatus.FAILED.value),
        **kwargs,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.id


def _set_status(db: Session, root_id: str, status: RootStatus) -> None:
    root = db.get(AuthorizedRoot, root_id)
    root.status = status.value
    db.commit()


def _root_of_version(db: Session, version_id: str) -> AuthorizedRoot:
    version = db.get(FileVersion, version_id)
    record = db.get(FileRecord, version.file_id)
    return db.get(AuthorizedRoot, record.root_id)


def test_mounts_lists_the_configured_read_only_mount(client, mount):
    response = client.get("/mounts")

    assert response.status_code == 200
    assert response.json() == [
        {
            "mount_id": "corpus",
            "label": "Course corpus",
            "read_only": True,
            "availability": "available",
        }
    ]


def test_directories_list_the_selected_folder_and_its_children(client, mount):
    response = client.get("/mounts/corpus/directories")

    assert response.status_code == 200
    paths = [item["relative_path"] for item in response.json()]
    # The folder itself comes first, then immediate children alphabetically;
    # hidden directories are not offered.
    assert paths == [".", "abnormal", "regression"]


def test_directories_of_a_nested_folder_are_relative_to_the_mount(client, mount):
    response = client.get("/mounts/corpus/directories", params={"relative_path": "regression"})

    assert response.status_code == 200
    assert response.json() == [{"relative_path": "regression", "label": "regression"}]


def test_directories_of_an_unknown_mount_is_a_coded_404(client, mount):
    response = client.get("/mounts/not-a-mount/directories")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_mount"


def test_directories_reject_a_path_escaping_the_mount(client, mount):
    response = client.get("/mounts/corpus/directories", params={"relative_path": "../etc"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_out_of_scope"


def test_authorizing_a_root_returns_the_flat_accepted_body(client, mount):
    payload = _create_root(client)

    assert set(payload) == {"root_id", "job_id", "status"}
    assert payload["status"] == "pending"


def test_authorizing_the_same_folder_twice_while_scanning_is_refused(client, mount):
    first = _create_root(client)

    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "."}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_job_exists"
    # Contract 6.2: the conflict carries the ids already accepted, so a client
    # whose first request timed out can attach to that work instead of guessing.
    assert detail["root_id"] == first["root_id"]
    assert detail["job_id"] == first["job_id"]


def test_reading_a_root_returns_status_availability_and_counts(client, mount, db_session):
    root_id = _create_root(client)["root_id"]

    response = client.get(f"/roots/{root_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["root_id"] == root_id
    assert body["status"] == "active"
    assert body["availability"] == "available"
    assert body["file_counts"] == {
        "total": 0,
        "discovered": 0,
        "extracting": 0,
        "basic_ready": 0,
        "enriched": 0,
        "failed": 0,
        "unsupported": 0,
    }


def test_reading_an_unknown_root_is_a_coded_404(client, mount):
    response = client.get("/roots/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "root_not_found"


def test_listing_roots_skips_revoked_folders(client, mount, db_session):
    kept = _create_root(client, "regression")["root_id"]
    revoked = _create_root(client, "abnormal")["root_id"]
    root = db_session.get(AuthorizedRoot, revoked)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    response = client.get("/roots")

    assert response.status_code == 200
    assert [item["root_id"] for item in response.json()] == [kept]


def test_rescanning_an_idle_root_queues_one_new_job(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    # The first scan finished in the worker, so nothing is live any more.
    first = db_session.query(Job).filter_by(root_id=root_id).one()
    first.status = JobStatus.COMPLETED.value
    db_session.commit()

    response = client.post(f"/roots/{root_id}/scans")

    assert response.status_code == 202
    body = response.json()
    assert body["root_id"] == root_id
    assert body["job_id"] != first.id
    assert body["status"] == "pending"


def test_rescanning_while_a_scan_is_live_is_refused(client, mount):
    first = _create_root(client)

    response = client.post(f"/roots/{first['root_id']}/scans")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_job_exists"
    assert detail["root_id"] == first["root_id"]
    assert detail["job_id"] == first["job_id"]


def test_authorizing_a_paused_folder_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    _set_status(db_session, root_id, RootStatus.PAUSED)
    jobs_before = db_session.query(Job).filter_by(root_id=root_id).count()

    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "."}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_paused"
    # A refused request must not leave work behind.
    assert db_session.query(Job).filter_by(root_id=root_id).count() == jobs_before


def test_authorizing_a_revoking_folder_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    _set_status(db_session, root_id, RootStatus.REVOKING)
    jobs_before = db_session.query(Job).filter_by(root_id=root_id).count()

    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "."}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_revoking"
    assert db_session.query(Job).filter_by(root_id=root_id).count() == jobs_before


def test_rescanning_a_revoked_root_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    root = db_session.get(AuthorizedRoot, root_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    response = client.post(f"/roots/{root_id}/scans")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_revoked"


def test_retrying_a_failed_job_requeues_it_and_keeps_attempts(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    job.attempts = 2
    job.error = "worker crashed"
    db_session.commit()
    job_id = job.id

    response = client.post(f"/jobs/{job_id}/retry")

    assert response.status_code == 202
    assert response.json() == {"job_id": job_id, "root_id": root_id, "status": "pending"}
    db_session.expire_all()
    retried = db_session.get(Job, job_id)
    assert retried.status == JobStatus.PENDING.value
    assert retried.attempts == 2
    assert retried.error is None


def test_retrying_a_completed_job_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.COMPLETED.value
    db_session.commit()

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "job_not_retryable"


def test_retrying_is_refused_when_the_target_already_has_a_live_job(
    client, mount, db_session
):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    db_session.commit()
    _make_job(
        db_session,
        root_id=root_id,
        status=JobStatus.PENDING.value,
        job_type=RootJobType.SCAN_ROOT.value,
    )

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "active_job_exists"


def test_a_claimed_job_is_reported_as_running_with_a_code_not_a_message(
    client, mount, db_session
):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.CLAIMED.value
    job.error = "Traceback: internal path /source/corpus leaked here"
    db_session.commit()

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert body["status"] == "running"
    # The diagnostic text stays in the database; only a stable code is public.
    assert body["error_code"] == "job_failed"
    assert "Traceback" not in response.text
    assert "/source/corpus" not in response.text


def test_a_missing_job_is_a_coded_404(client, mount):
    response = client.get("/jobs/999999")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_not_found"


def test_the_authorized_root_is_reachable_on_disk_for_the_worker(mount):
    """Guard for the fixture itself: the mounted path must really exist."""
    assert Path(mount).is_dir()


def test_retrying_a_job_of_a_paused_root_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    db_session.commit()
    _set_status(db_session, root_id, RootStatus.PAUSED)

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_paused"
    # The refused retry must leave the job where it was.
    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value


def test_retrying_a_job_of_a_revoking_root_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    db_session.commit()
    _set_status(db_session, root_id, RootStatus.REVOKING)

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_revoking"
    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value
    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value


def test_retrying_a_job_of_a_revoked_root_is_refused(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    db_session.commit()
    _set_status(db_session, root_id, RootStatus.REVOKED)

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_revoked"
    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value
    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value


def test_retrying_an_embed_job_finds_its_root_through_the_version(
    client, mount, db_session, make_file_version
):
    """Embed jobs carry only version_id; the lifecycle check must still apply."""
    version_id = make_file_version(sha256="c" * 64)
    job_id = _make_job(
        db_session, job_type=RootJobType.EMBED_FILE.value, version_id=version_id
    )
    root = _root_of_version(db_session, version_id)
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    response = client.post(f"/jobs/{job_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "root_revoked"


def test_retrying_a_case_job_keeps_the_starter_behaviour(client, db_session):
    """Case jobs have no root; the lifecycle check must not block them."""
    created = client.post(
        "/cases",
        json={"title": "Printer offline", "description": "The office printer is unreachable."},
    ).json()
    job_id = created["job"]["job_id"]
    job = db_session.get(Job, job_id)
    job.status = JobStatus.FAILED.value
    db_session.commit()

    response = client.post(f"/jobs/{job_id}/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_retrying_is_refused_with_the_blocking_job_id(client, mount, db_session):
    root_id = _create_root(client)["root_id"]
    job = db_session.query(Job).filter_by(root_id=root_id).one()
    job.status = JobStatus.FAILED.value
    db_session.commit()
    blocker_id = _make_job(
        db_session, root_id=root_id, status=JobStatus.PENDING.value
    )

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "active_job_exists"
    assert detail["root_id"] == root_id
    assert detail["job_id"] == blocker_id
