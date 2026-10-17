"""Backend M1 proof using D's frozen 12/3/1 corpus and five keyword queries."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
)
from services.worker.app import main as worker

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures"
GOLD = ROOT / "tests" / "fixtures" / "w7-gold-queries.json"


def _copy_corpus(target: Path) -> None:
    for category in ("normal", "abnormal", "unsupported"):
        shutil.copytree(CORPUS / category, target / category)


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_frozen_corpus_runs_the_m1_keyword_evidence_flow(
    client, db_session: Session, tmp_path: Path, monkeypatch
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _copy_corpus(corpus)
    before_hashes = _hashes(corpus)

    monkeypatch.setattr(worker.settings, "source_mounts", {"demo": str(tmp_path)})
    monkeypatch.setattr(
        worker,
        "get_session_factory",
        lambda: lambda: contextlib.nullcontext(db_session),
    )

    created = client.post(
        "/roots",
        json={"mount_id": "demo", "relative_path": "corpus"},
    )
    assert created.status_code == 202
    created_payload = created.json()
    worker.process_job(created_payload["job_id"])

    db_session.expire_all()
    extract_jobs = (
        db_session.execute(
            select(Job).where(Job.job_type == RootJobType.EXTRACT_FILE.value)
        )
        .scalars()
        .all()
    )
    assert len(extract_jobs) == 16
    for job in extract_jobs:
        worker.process_job(job.id)

    db_session.expire_all()
    assert len(db_session.execute(select(FileRecord)).scalars().all()) == 16
    assert len(db_session.execute(select(FileVersion)).scalars().all()) == 16
    assert all(
        db_session.get(Job, job.id).status == JobStatus.COMPLETED.value
        for job in extract_jobs
    )

    listed = client.get(
        "/files",
        params={"root_id": created_payload["root_id"]},
    ).json()
    assert len(listed) == 16
    basic_ready = [item for item in listed if item["status"] == "basic_ready"]
    unsupported = [item for item in listed if item["status"] == "unsupported"]
    assert len(basic_ready) == 12
    assert len(unsupported) == 4
    assert all(item["error_code"] for item in unsupported)

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    keyword_queries = [
        query for query in gold["queries"] if query["kind"] == "keyword"
    ]
    assert len(keyword_queries) == 5
    for query in keyword_queries:
        response = client.post(
            "/search",
            json={
                "query": query["query"],
                "mode": "keyword",
                "root_id": created_payload["root_id"],
                "top_k": 10,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        expected = query["expected"][0]
        assert payload["results"], query["query_id"]
        hit = payload["results"][0]
        assert hit["file_path"] == expected["relative_path"], query["query_id"]
        assert hit["page"] == expected["page"], query["query_id"]

        evidence = client.get(f"/evidence/{hit['chunk_id']}")
        assert evidence.status_code == 200
        assert evidence.json()["page_number"] == expected["page"]

    repeated = client.post(
        "/roots",
        json={"mount_id": "demo", "relative_path": "corpus"},
    )
    assert repeated.status_code == 202
    worker.process_job(repeated.json()["job_id"])
    db_session.expire_all()

    assert len(db_session.execute(select(FileRecord)).scalars().all()) == 16
    assert len(db_session.execute(select(FileVersion)).scalars().all()) == 16
    assert (
        len(
            db_session.execute(
                select(Job).where(Job.job_type == RootJobType.EXTRACT_FILE.value)
            )
            .scalars()
            .all()
        )
        == 16
    )
    assert _hashes(corpus) == before_hashes
