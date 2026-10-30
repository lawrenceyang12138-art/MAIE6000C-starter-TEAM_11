"""The explicit page-count command preserves canonical evidence and vector indexes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from scripts import search_tools
from services.common.config import Settings
from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    SourceChunk,
)
from services.parsing.handler import handle_extract_file
from services.scan import handler as scan_handler
from services.search.indexing import embed_version
from services.search.page_metadata import VersionPageMetadata
from services.search.text import MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ScannedCorpus:
    database_url: str
    root_id: str
    other_root_id: str
    version_ids: dict[str, str]
    paths: dict[str, Path]
    mount: Path


class _MutationSentinelBackend:
    """Known vectors let preservation checks run without loading any model."""

    model_id, dimensions = MODEL_ID, TOKEN_DIMENSIONS

    def embed(self, texts, kind="passage"):
        return [[[1.0] + [0.0] * (TOKEN_DIMENSIONS - 1)] for _ in texts]


def _write_pdf(path: Path, pages: int) -> None:
    with pymupdf.open() as document:
        for index in range(pages):
            page = document.new_page()
            if index == 0:
                page.insert_text((72, 72), f"Original searchable evidence for {path.name}.")
        document.save(path)


@pytest.fixture()
def scanned_corpus(db_session, tmp_path, monkeypatch):
    mount = tmp_path / "sources"
    roots = {}
    versions = {}
    paths = {}
    mounts = {"page-metadata-cli": str(mount)}
    settings = Settings(_env_file=None, source_mounts=mounts)
    monkeypatch.setenv("SOURCE_MOUNTS", json.dumps(mounts))
    monkeypatch.setattr(scan_handler, "get_settings", lambda: settings)
    for relative_root, documents in (
        ("allowed", {"a-good.pdf": 4, "z-changed.pdf": 3}),
        ("other", {"other.pdf": 2}),
    ):
        directory = mount / relative_root
        directory.mkdir(parents=True)
        for filename, pages in documents.items():
            path = directory / filename
            _write_pdf(path, pages)
            paths[f"{relative_root}/{filename}"] = path
        root = AuthorizedRoot(
            mount_id="page-metadata-cli", relative_path=relative_root, status="active",
        )
        db_session.add(root)
        db_session.commit()
        roots[relative_root] = root.id
        summary = scan_handler.handle_scan_root(db_session, root.id)
        assert summary["files_created"] == len(documents)
        records = list(db_session.scalars(select(FileRecord).where(FileRecord.root_id == root.id)))
        for record in records:
            version_id = record.current_version_id
            path = directory / record.relative_path
            assert handle_extract_file(db_session, version_id, path) == "basic_ready"
            result = embed_version(db_session, version_id, _MutationSentinelBackend())
            assert result.embedded_count > 0 and result.embedding_error is None
            versions[f"{relative_root}/{record.relative_path}"] = version_id
        db_session.commit()
    # Simulate an already indexed corpus predating the page-count policy.
    db_session.execute(delete(VersionPageMetadata))
    db_session.commit()
    return ScannedCorpus(
        str(db_session.get_bind().url), roots["allowed"], roots["other"], versions, paths, mount,
    )


def _evidence_snapshot(db):
    return {
        model.__tablename__: db.execute(
            select(model.__table__).order_by(*model.__table__.primary_key.columns)
        ).all()
        for model in (FileRecord, FileVersion, SourceChunk, ChunkSearchIndex, ChunkTokenIndex)
    }


def _page_counts(db):
    return dict(db.execute(select(
        VersionPageMetadata.version_id, VersionPageMetadata.page_count,
    )).all())


def _forbid_work(*args, **kwargs):
    pytest.fail("rejected commands must not access the database, sources, or AI")


def test_missing_root_is_rejected_before_database_or_ai(tmp_path, monkeypatch, capsys):
    database = tmp_path / "must-not-exist.db"
    monkeypatch.setattr(sys, "argv", [
        "search_tools", "page-metadata", "--database-url", f"sqlite:///{database}",
        "--output", str(tmp_path / "report.json"),
    ])
    for name in ("make_engine", "LocalPplxEmbeddingBackend", "HTTPEmbeddingBackend"):
        monkeypatch.setattr(search_tools, name, _forbid_work)
    with pytest.raises(SystemExit) as error:
        search_tools.main()
    assert error.value.code == 2
    assert "page-metadata requires --root-id" in capsys.readouterr().err
    assert not database.exists()
    assert not (tmp_path / "report.json").exists()


def test_version_in_another_root_is_rejected_before_preparation(
    db_session, scanned_corpus, monkeypatch,
):
    before = _evidence_snapshot(db_session)
    monkeypatch.setattr(search_tools, "prepare_version_page_metadata", _forbid_work)
    with pytest.raises(ValueError, match="page_metadata_version_outside_scope"):
        search_tools.backfill_page_metadata(
            scanned_corpus.database_url, scanned_corpus.root_id,
            scanned_corpus.version_ids["other/other.pdf"],
        )
    assert _page_counts(db_session) == {}
    assert _evidence_snapshot(db_session) == before


@pytest.mark.parametrize("status", ["revoked", "revoking"])
def test_unreadable_root_is_rejected_before_preparation(
    db_session, scanned_corpus, monkeypatch, status,
):
    root = db_session.get(AuthorizedRoot, scanned_corpus.root_id)
    root.status = status
    db_session.commit()
    before = _evidence_snapshot(db_session)
    monkeypatch.setattr(search_tools, "prepare_version_page_metadata", _forbid_work)
    with pytest.raises(ValueError, match="page_metadata_root_not_readable"):
        search_tools.backfill_page_metadata(
            scanned_corpus.database_url, scanned_corpus.root_id, None,
        )
    assert _page_counts(db_session) == {}
    assert _evidence_snapshot(db_session) == before


def test_database_failure_propagates_and_rolls_back_prior_metadata(
    db_session, scanned_corpus, monkeypatch,
):
    before = _evidence_snapshot(db_session)
    original = search_tools.prepare_version_page_metadata
    prepared = []

    def fail_second(db, version_id):
        if prepared:
            raise SQLAlchemyError("injected metadata database failure")
        result = original(db, version_id)
        assert result.error is None
        prepared.append(version_id)
        return result

    monkeypatch.setattr(search_tools, "prepare_version_page_metadata", fail_second)
    with pytest.raises(SQLAlchemyError, match="injected metadata database failure"):
        search_tools.backfill_page_metadata(
            scanned_corpus.database_url, scanned_corpus.root_id, None,
        )
    assert len(prepared) == 1
    assert _page_counts(db_session) == {}
    assert _evidence_snapshot(db_session) == before


def test_report_inside_configured_source_mount_is_refused_before_database_access(
    scanned_corpus, monkeypatch, capsys,
):
    output = scanned_corpus.mount / "unsafe-report.json"
    monkeypatch.setattr(sys, "argv", [
        "search_tools", "page-metadata", "--root-id", scanned_corpus.root_id,
        "--database-url", scanned_corpus.database_url, "--output", str(output),
    ])
    monkeypatch.setattr(search_tools, "backfill_page_metadata", _forbid_work)
    monkeypatch.setattr(search_tools, "LocalPplxEmbeddingBackend", _forbid_work)
    with pytest.raises(SystemExit) as error:
        search_tools.main()
    assert error.value.code == 2
    assert "output_path_inside_source" in capsys.readouterr().err
    assert not output.exists()


def test_real_cli_preserves_evidence_and_reports_changed_source_separately(
    db_session, scanned_corpus, tmp_path,
):
    corpus = scanned_corpus
    good_id = corpus.version_ids["allowed/a-good.pdf"]
    changed_id = corpus.version_ids["allowed/z-changed.pdf"]
    before = _evidence_snapshot(db_session)
    assert before[ChunkTokenIndex.__tablename__]
    source_bytes = {key: path.read_bytes() for key, path in corpus.paths.items()}
    # Only page one has text; the physical blank tail must still count.
    pages_with_text = set(db_session.scalars(select(SourceChunk.page_number).where(
        SourceChunk.version_id == good_id,
    )))
    assert pages_with_text == {1}
    output = tmp_path / "report.json"
    arguments = [
        sys.executable, "-m", "scripts.search_tools", "page-metadata",
        "--database-url", corpus.database_url, "--root-id", corpus.root_id,
        "--model-path", str(tmp_path / "model-does-not-exist"), "--output", str(output),
    ]
    environment = {
        **os.environ, "SOURCE_MOUNTS": json.dumps({"page-metadata-cli": str(corpus.mount)}),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUTF8": "1",
    }

    def run(extra_arguments):
        return subprocess.run(
            [*arguments, *extra_arguments], cwd=REPO, env=environment,
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=60,
        )

    for _ in range(2):
        completed = run(["--version-id", good_id])
        assert completed.returncode == 0, completed.stderr
        report = json.loads(output.read_text(encoding="utf-8"))
        assert json.loads(completed.stdout) == report
        assert report["passed"] and report["selected_current_versions"] == 1
        assert report["ready_versions"] == 1 and report["error_versions"] == 0
        assert report["versions"] == [{"version_id": good_id, "page_count": 4, "error": None}]
        assert "page-metadata" in report["command"]
        assert {"sha", "branch", "source_sha256"} <= report["git"].keys()
        assert _page_counts(db_session) == {good_id: 4}
        assert _evidence_snapshot(db_session) == before
        assert {key: path.read_bytes() for key, path in corpus.paths.items()} == source_bytes

    changed = corpus.paths["allowed/z-changed.pdf"]
    changed.write_bytes(changed.read_bytes() + b"\nchanged after scan")
    completed = run([])
    assert completed.returncode == 1, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert not report["passed"] and report["selected_current_versions"] == 2
    assert report["ready_versions"] == 1 and report["error_versions"] == 1
    results = {item["version_id"]: item for item in report["versions"]}
    assert results[good_id] == {"version_id": good_id, "page_count": 4, "error": None}
    assert results[changed_id] == {
        "version_id": changed_id, "page_count": None, "error": "page_metadata_source_changed",
    }
    assert _page_counts(db_session) == {good_id: 4}
    assert _evidence_snapshot(db_session) == before
    assert corpus.paths["allowed/a-good.pdf"].read_bytes() == source_bytes["allowed/a-good.pdf"]
    assert corpus.paths["other/other.pdf"].read_bytes() == source_bytes["other/other.pdf"]
