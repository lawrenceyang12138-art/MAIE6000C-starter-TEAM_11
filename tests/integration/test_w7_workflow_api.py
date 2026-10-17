"""Minimum W7 browser workflow: mounts, current search and evidence."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from services.api.app.main import app
from services.common.config import Settings, get_settings
from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootStatus,
    VersionStatus,
)
from services.parsing.chunking import Chunk
from services.parsing.persist import persist_chunks


def _ready_file(
    db: Session,
    make_file_version,
    *,
    sha256: str,
    text: str,
    page: int,
) -> tuple[str, str, str]:
    version_id = make_file_version(sha256=sha256)
    version = db.get(FileVersion, version_id)
    version.status = VersionStatus.BASIC_READY.value
    file_record = db.get(FileRecord, version.file_id)
    file_record.current_version_id = version_id
    db.commit()
    persist_chunks(
        db,
        version_id,
        [Chunk(ordinal=1, page_number=page, text=text)],
    )
    return version_id, file_record.id, file_record.root_id


def test_mount_list_and_directory_discovery(client, tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "visible").mkdir(parents=True)
    (corpus / ".hidden").mkdir()
    (corpus / "linked").symlink_to(tmp_path, target_is_directory=True)
    settings = Settings(
        source_mounts={"corpus": str(corpus)},
        _env_file=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    try:
        mounts = client.get("/mounts")
        directories = client.get("/mounts/corpus/directories")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert mounts.status_code == 200
    assert mounts.json() == [
        {
            "mount_id": "corpus",
            "label": "corpus",
            "read_only": True,
            "availability": "available",
        }
    ]
    assert directories.status_code == 200
    assert directories.json() == [
        {"relative_path": ".", "label": "corpus"},
        {"relative_path": "visible", "label": "visible"},
    ]


def test_root_creation_is_flat_and_job_status_uses_public_vocabulary(
    client, db_session: Session
):
    created = client.post(
        "/roots",
        json={"mount_id": "corpus", "relative_path": "docs"},
    )

    assert created.status_code == 202
    payload = created.json()
    assert set(payload) == {"root_id", "job_id", "status"}
    assert payload["status"] == "pending"

    job = db_session.get(Job, payload["job_id"])
    assert job.job_type == "scan_root"
    job.status = JobStatus.CLAIMED.value
    db_session.commit()

    job_response = client.get(f"/jobs/{payload['job_id']}")
    assert job_response.status_code == 200
    assert job_response.json()["job_id"] == payload["job_id"]
    assert job_response.json()["status"] == "running"

    root_response = client.get(f"/roots/{payload['root_id']}")
    assert root_response.status_code == 200
    assert root_response.json()["root_id"] == payload["root_id"]
    assert root_response.json()["file_counts"]["total"] == 0
    assert client.get("/roots").json() == [root_response.json()]

    second = client.post(
        "/roots",
        json={"mount_id": "corpus", "relative_path": "docs"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "active_job_exists"


def test_keyword_search_reads_only_current_authorized_chunks(
    client, db_session: Session, make_file_version
):
    version_id, file_id, root_id = _ready_file(
        db_session,
        make_file_version,
        sha256="a" * 64,
        text="Database backup instructions and recovery steps",
        page=3,
    )

    response = client.post(
        "/search",
        json={"query": "database backup", "mode": "keyword", "top_k": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_mode"] == "keyword"
    assert payload["degraded"] is False
    assert payload["total"] == 1
    result = payload["results"][0]
    assert (result["root_id"], result["file_id"], result["version_id"]) == (
        root_id,
        file_id,
        version_id,
    )
    assert result["page"] == 3
    assert result["text"].startswith("Database backup")

    evidence = client.get(f"/evidence/{result['chunk_id']}")
    assert evidence.status_code == 200
    assert evidence.json()["text"] == result["text"]

    file_record = db_session.get(FileRecord, file_id)
    file_record.presence_status = FilePresence.MISSING.value
    db_session.commit()
    assert client.post(
        "/search", json={"query": "backup", "mode": "keyword"}
    ).json()["total"] == 0


def test_hybrid_search_degrades_to_keyword(
    client, db_session: Session, make_file_version
):
    _ready_file(
        db_session,
        make_file_version,
        sha256="b" * 64,
        text="Recovery procedure",
        page=1,
    )

    response = client.post(
        "/search",
        json={"query": "recovery", "mode": "hybrid"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_mode"] == "keyword"
    assert payload["degraded"] is True
    assert payload["degradation_reason"] in {"ai_unavailable", "ai_disabled"}


def test_search_excludes_revoked_roots(
    client, db_session: Session, make_file_version
):
    _ready_file(
        db_session,
        make_file_version,
        sha256="c" * 64,
        text="Secret recovery notes",
        page=1,
    )
    root = db_session.query(AuthorizedRoot).one()
    root.status = RootStatus.REVOKED.value
    db_session.commit()

    assert client.post(
        "/search", json={"query": "recovery", "mode": "keyword"}
    ).json()["total"] == 0


def test_failed_job_can_be_explicitly_retried_without_losing_attempts(
    client, db_session: Session
):
    root = AuthorizedRoot(
        mount_id="retry-test",
        relative_path=".",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(root)
    db_session.flush()
    job = Job(
        root_id=root.id,
        job_type="scan_root",
        status=JobStatus.FAILED.value,
        attempts=2,
        error="temporary_worker_failure",
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/jobs/{job.id}/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["error"] is None
    assert payload["attempts"] == 2
    assert client.post(f"/jobs/{job.id}/retry").status_code == 409
