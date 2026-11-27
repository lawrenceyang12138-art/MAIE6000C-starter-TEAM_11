"""End-to-end recovery: authorize, scan, fail, restore, retry, parse.

This is the loop the A2 requirement is about, run through the real HTTP
handlers, the real scan handler, the real extraction handler and the real
worker dispatch, against a real (temporary) corpus and a real database. Only
the worker's session factory and the mount allowlist are pointed at the test
double; nothing in the pipeline is stubbed.

Fault injection is confined to files under ``tmp_path``, leaving the repository
fixtures unchanged.
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.db import make_session_factory
from services.common.models import (
    ChunkSearchIndex,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    SourceChunk,
    VersionStatus,
)
from services.parsing.pdf import (
    REASON_ENCRYPTED,
    REASON_FILE_MISSING,
    REASON_NO_TEXT_LAYER,
    REASON_SOURCE_CHANGED,
    REASON_UNREADABLE,
)
from services.parsing.text import REASON_TEXT_EMPTY, REASON_TEXT_TOO_LARGE, TEXT_MAX_BYTES
from services.scan import handler as scan_handler
from services.worker.app import main as worker_main

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / "normal.pdf"
DOCUMENT = "lecture.pdf"


def _docx_with_text(text: str) -> bytes:
    buffer = io.BytesIO()
    # Store the XML as-is so equal-length passages yield equal-size files.
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
            '2006/main"><w:body><w:p><w:r><w:t>'
            f"{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


@pytest.fixture()
def source_mount(tmp_path, monkeypatch, db_session: Session):
    """A writable, allowlisted directory shared by the API, scanner and worker."""
    root = tmp_path / "corpus"
    root.mkdir()

    # Search, scan and the worker must see the same allowlisted source.
    monkeypatch.setattr(get_settings(), "source_mounts", {"corpus": str(root)})

    factory = make_session_factory(db_session.get_bind())
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: factory)
    return root


@pytest.fixture()
def corpus(source_mount):
    """A writable copy of one real PDF, served as the allowlisted mount."""
    shutil.copyfile(FIXTURE_PDF, source_mount / DOCUMENT)
    return source_mount


@pytest.fixture()
def text_source(source_mount, monkeypatch):
    monkeypatch.setenv("TEXT_PARSING_ENABLED", "true")
    monkeypatch.setenv("TEXT_MAX_BYTES", "128")
    return source_mount / "notes.txt"


def _authorize(client) -> tuple[str, int]:
    response = client.post(
        "/roots", json={"mount_id": "corpus", "relative_path": "."}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    return body["root_id"], body["job_id"]


def _open_jobs(db: Session, **filters) -> list[Job]:
    return list(
        db.execute(
            select(Job).filter_by(status=JobStatus.PENDING.value, **filters)
        ).scalars()
    )


def _run_next_job(db: Session) -> Job:
    """Claim and run one job the way the worker loop does.

    The claim is part of the contract under test: it is what records the
    attempt, so calling the handler directly would hide whether attempts are
    preserved across a retry.
    """
    job = worker_main.claim_next_pending_job(db)
    assert job is not None, "expected a pending job to claim"
    worker_main.process_job(job.job_id, job)
    return job


def _extract_jobs(db: Session, version_id: str) -> list[Job]:
    return list(
        db.execute(
            select(Job).where(
                Job.version_id == version_id,
                Job.job_type == RootJobType.EXTRACT_FILE.value,
            )
        ).scalars()
    )


def _only_file(db: Session) -> FileRecord:
    return db.execute(select(FileRecord)).scalars().one()


def _version_of(db: Session, record: FileRecord) -> FileVersion:
    return db.get(FileVersion, record.current_version_id)


def _scan_and_collect(db: Session, client, root_id: str) -> int:
    """Queue another scan through the API and return its job id."""
    response = client.post(f"/roots/{root_id}/scans")
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_a_temporary_source_loss_recovers_through_an_explicit_retry(client, corpus, db_session):
    """The whole loop: scan, fail on a vanished file, restore, retry, parse.

    Before this change the failure was recorded on the version while the job
    said ``completed``, so the retry endpoint refused it and restoring the file
    changed nothing: the version stayed ``failed`` for good.
    """
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)

    record = _only_file(db_session)
    version = _version_of(db_session, record)
    assert version.status == VersionStatus.DISCOVERED.value
    extract_job = _extract_jobs(db_session, version.id)
    assert len(extract_job) == 1
    extract_job_id = extract_job[0].id
    sha_before = version.content_sha256

    # The source goes away between the scan and the extraction.
    (corpus / DOCUMENT).unlink()
    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version.id)
    failed_job = db_session.get(Job, extract_job_id)
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == REASON_FILE_MISSING
    # The job must fail too, otherwise it can never be retried.
    assert failed_job.status == JobStatus.FAILED.value
    assert failed_job.error_code == REASON_FILE_MISSING
    assert failed_job.attempts == 1

    # The API says the same thing, with a stable code and no diagnostic text.
    body = client.get(f"/jobs/{extract_job_id}").json()
    assert body["status"] == "failed"
    assert body["error_code"] == REASON_FILE_MISSING
    assert body["attempts"] == 1

    # Same bytes come back. A rescan sees the same content, so it adds no
    # version and queues no second extraction.
    shutil.copyfile(FIXTURE_PDF, corpus / DOCUMENT)
    rescan_job_id = _scan_and_collect(db_session, client, root_id)
    worker_main.process_job(rescan_job_id)

    db_session.expire_all()
    record = _only_file(db_session)
    assert record.presence_status == FilePresence.PRESENT.value
    assert record.presence_reason is None
    assert record.current_version_id == version.id
    assert len(_extract_jobs(db_session, version.id)) == 1
    assert _version_of(db_session, record).content_sha256 == sha_before
    # Still failed: a scan is not an implicit retry.
    assert _version_of(db_session, record).status == VersionStatus.FAILED.value

    # The explicit retry is what reprocesses it.
    retry = client.post(f"/jobs/{extract_job_id}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json() == {
        "job_id": extract_job_id,
        "root_id": root_id,
        "status": "pending",
    }

    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version.id)
    job = db_session.get(Job, extract_job_id)
    assert version.status == VersionStatus.BASIC_READY.value
    assert version.error_code is None
    assert version.parser_revision is not None
    assert job.status == JobStatus.COMPLETED.value
    assert job.error_code is None
    # Attempts are provenance: the second run adds one, none are lost.
    assert job.attempts == 2

    chunks = db_session.execute(
        select(SourceChunk).where(SourceChunk.version_id == version.id)
    ).scalars().all()
    assert chunks, "the recovered version must carry its extracted text"
    # Re-processing did not duplicate passages: ordinals stay unique per version.
    ordinals = [chunk.ordinal for chunk in chunks]
    assert len(ordinals) == len(set(ordinals))

    # Source text is stored, so the search index job is queued - and only one.
    embed_jobs = _open_jobs(
        db_session,
        version_id=version.id,
        job_type=RootJobType.EMBED_FILE.value,
    )
    assert len(embed_jobs) == 1


def test_a_retry_while_the_file_is_still_gone_fails_again_and_stays_retryable(
    client, corpus, db_session
):
    """Repeating a retry is idempotent: one job row, more attempts, no copies."""
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    extract_job_id = _extract_jobs(db_session, version.id)[0].id

    (corpus / DOCUMENT).unlink()
    _run_next_job(db_session)
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 202

    # The file is still gone: the retry fails the same way, and stays retryable.
    _run_next_job(db_session)

    db_session.expire_all()
    job = db_session.get(Job, extract_job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.error_code == REASON_FILE_MISSING
    assert job.attempts == 2
    assert len(_extract_jobs(db_session, version.id)) == 1

    # A third explicit retry is still accepted, so the loop never dead-ends.
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 202


@pytest.mark.parametrize(
    "replacement",
    [
        b"", b"\xff" * len(b"restore this passage"), b"x" * 129,
        FIXTURE_PDF.with_name("no_text_layer.pdf"), FIXTURE_PDF.with_name("encrypted.pdf"),
    ],
    ids=["empty", "same-size-invalid-utf8", "too-large", "image-pdf", "encrypted-pdf"],
)
def test_a_changed_text_rejection_can_retry_the_original_version(
    client, text_source, db_session, replacement
):
    original = b"restore this passage"
    text_source.write_bytes(original)
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version_id = _version_of(db_session, _only_file(db_session)).id
    (job,) = _extract_jobs(db_session, version_id)
    extract_job_id = job.id

    if isinstance(replacement, Path):
        replacement = replacement.read_bytes()
    text_source.write_bytes(replacement)
    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    job = client.get(f"/jobs/{extract_job_id}").json()
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == job["error_code"] == REASON_SOURCE_CHANGED
    assert job["status"] == JobStatus.FAILED.value
    assert db_session.query(SourceChunk).filter_by(version_id=version_id).count() == 0

    text_source.write_bytes(original)
    worker_main.process_job(_scan_and_collect(db_session, client, root_id))
    db_session.expire_all()
    assert _only_file(db_session).current_version_id == version_id
    assert [job.id for job in _extract_jobs(db_session, version_id)] == [extract_job_id]
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 202
    _run_next_job(db_session)

    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.BASIC_READY.value
    assert version.error_code is None
    assert client.get(f"/jobs/{extract_job_id}").json()["attempts"] == 2
    chunk = db_session.query(SourceChunk).filter_by(version_id=version_id).one()
    assert chunk.text == original.decode()
    response = client.post("/search", json={"query": "restore", "mode": "keyword"})
    assert response.status_code == 200
    assert [hit["version_id"] for hit in response.json()["results"]] == [version_id]


@pytest.mark.parametrize(
    ("content", "reason_code"),
    [
        (b"", REASON_TEXT_EMPTY), (b"x" * (TEXT_MAX_BYTES + 1), REASON_TEXT_TOO_LARGE),
        (FIXTURE_PDF.with_name("no_text_layer.pdf"), REASON_NO_TEXT_LAYER),
        (FIXTURE_PDF.with_name("encrypted.pdf"), REASON_ENCRYPTED),
    ],
    ids=["empty", "too-large", "image-pdf", "encrypted-pdf"],
)
def test_unchanged_rejected_text_remains_unsupported(
    client, text_source, db_session, content, reason_code
):
    text_source.write_bytes(content.read_bytes() if isinstance(content, Path) else content)
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version_id = _version_of(db_session, _only_file(db_session)).id
    (job,) = _extract_jobs(db_session, version_id)
    extract_job_id = job.id
    _run_next_job(db_session)

    db_session.expire_all()
    (row,) = client.get("/files", params={"root_id": root_id}).json()
    assert row["version_id"] == version_id
    assert row["status"] == VersionStatus.UNSUPPORTED.value
    assert row["error_code"] == reason_code
    assert client.get(f"/jobs/{extract_job_id}").json()["status"] == JobStatus.COMPLETED.value
    assert client.post(f"/jobs/{extract_job_id}/retry").status_code == 409


@pytest.mark.parametrize("action", ["replace", "remove"])
def test_source_changed_after_parser_rejection_is_retryable(
    client, text_source, db_session, monkeypatch, tmp_path, action
):
    from services.parsing import handler
    from services.parsing.pdf import UnsupportedDocument

    original = b" " * len(b"valid text")
    text_source.write_bytes(original)
    _, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version_id = _version_of(db_session, _only_file(db_session)).id
    (job,) = _extract_jobs(db_session, version_id)
    job_id = job.id
    real_extract = handler.extract_document

    def reject_then_change(*args, **kwargs):
        try:
            return real_extract(*args, **kwargs)
        except UnsupportedDocument as exc:
            assert exc.reason_code == REASON_TEXT_EMPTY
            if action == "replace":
                replacement = tmp_path / "replacement.txt"
                replacement.write_bytes(b"valid text")
                replacement.replace(text_source)
            else:
                text_source.unlink()
            raise

    with monkeypatch.context() as patch:
        patch.setattr(handler, "extract_document", reject_then_change)
        _run_next_job(db_session)
    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    job = client.get(f"/jobs/{job_id}").json()
    expected = REASON_SOURCE_CHANGED if action == "replace" else REASON_FILE_MISSING
    assert (version.status, version.error_code) == (VersionStatus.FAILED.value, expected)
    assert (job["status"], job["error_code"]) == (JobStatus.FAILED.value, expected)
    assert not db_session.query(SourceChunk).filter_by(version_id=version_id).count()
    text_source.write_bytes(original)
    assert client.post(f"/jobs/{job_id}/retry").status_code == 202
    _run_next_job(db_session)
    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    assert (version.status, version.error_code) == (
        VersionStatus.UNSUPPORTED.value, REASON_TEXT_EMPTY
    )


@pytest.mark.parametrize("original_is_pdf", [False, True], ids=["txt", "pdf-named-txt"])
@pytest.mark.parametrize("fault", ["replacement", "open-error", "read-error"])
def test_format_detection_uses_the_parser_snapshot_and_is_retryable(
    client, text_source, db_session, monkeypatch, original_is_pdf, fault
):
    pdf = FIXTURE_PDF.read_bytes()
    txt = b"restorable document"
    original, other = (pdf, txt) if original_is_pdf else (txt, pdf)
    text_source.write_bytes(original)
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version_id = _version_of(db_session, _only_file(db_session)).id
    (job,) = _extract_jobs(db_session, version_id)
    job_id = job.id

    monkeypatch.setenv("TEXT_MAX_BYTES", str(max(len(pdf), len(txt))))
    real_open = Path.open
    injected = False

    class InterruptedRead(io.BytesIO):
        def read(self, size=-1):
            raise OSError("temporary mount read failure")

    def open_once(path, mode="r", *args, **kwargs):
        nonlocal injected
        if path == text_source and mode == "rb" and not injected:
            injected = True
            if fault == "open-error":
                raise PermissionError("temporary mount open failure")
            if fault == "read-error":
                return InterruptedRead()
            # A handle on the displaced file; subsequent opens see the restored original.
            return io.BytesIO(other)
        return real_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_once)
        _run_next_job(db_session)
    assert injected
    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    job = client.get(f"/jobs/{job_id}").json()
    expected = REASON_SOURCE_CHANGED if fault == "replacement" else REASON_UNREADABLE
    assert (version.status, version.error_code) == (VersionStatus.FAILED.value, expected)
    assert (job["status"], job["error_code"]) == (JobStatus.FAILED.value, expected)
    assert not db_session.query(SourceChunk).filter_by(version_id=version_id).count()

    worker_main.process_job(_scan_and_collect(db_session, client, root_id))
    assert [j.id for j in _extract_jobs(db_session, version_id)] == [job_id]
    assert client.post(f"/jobs/{job_id}/retry").status_code == 202
    _run_next_job(db_session)
    query = "alpha" if original_is_pdf else "restorable"
    result = client.post("/search", json={"query": query, "mode": "keyword"})
    assert result.status_code == 200
    assert [hit["version_id"] for hit in result.json()["results"]] == [version_id]


@pytest.mark.parametrize("extension", ["txt", "md", "docx"])
@pytest.mark.parametrize("replace_at", ["reader_return", "index_stage"])
def test_replaced_native_source_is_not_published(
    client, source_mount, db_session, monkeypatch, tmp_path, extension, replace_at
):
    monkeypatch.setenv("TEXT_PARSING_ENABLED", "true")
    monkeypatch.setenv("DOCX_PARSING_ENABLED", "true")
    monkeypatch.setenv("TEXT_MAX_BYTES", "4096")
    source = source_mount / f"notes.{extension}"
    original_text = "original searchable passage"
    replacement_text = "modified searchable passage"
    if extension == "docx":
        original = _docx_with_text(original_text)
        replacement = _docx_with_text(replacement_text)
    else:
        original = original_text.encode()
        replacement = replacement_text.encode()
    assert len(original) == len(replacement)
    source.write_bytes(original)

    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version_id = _version_of(db_session, _only_file(db_session)).id
    (extract_job,) = _extract_jobs(db_session, version_id)

    import services.parsing.handler as handler_module
    import services.parsing.pdf as pdf_module

    real_read = pdf_module.read_source_snapshot
    real_prepare_indexes = handler_module.prepare_keyword_indexes
    replacement_path = tmp_path / f"replacement.{extension}"
    replaced = False

    def replace_source():
        nonlocal replaced
        if not replaced:
            replacement_path.write_bytes(replacement)
            replacement_path.replace(source)
            replaced = True

    def read_then_replace(path, **kwargs):
        snapshot = real_read(path, **kwargs)
        if replace_at == "reader_return" and Path(path) == source:
            # Replace after acquiring the bytes but before returning the
            # snapshot. Windows does not allow renaming its open handle.
            replace_source()
        return snapshot

    def index_then_replace(db, target_version_id):
        real_prepare_indexes(db, target_version_id)
        if replace_at == "index_stage":
            assert db.query(ChunkSearchIndex).count() == 1
            replace_source()

    monkeypatch.setattr(pdf_module, "read_source_snapshot", read_then_replace)
    monkeypatch.setattr(handler_module, "prepare_keyword_indexes", index_then_replace)
    _run_next_job(db_session)
    assert replaced

    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    job = client.get(f"/jobs/{extract_job.id}").json()
    assert version.status == VersionStatus.FAILED.value
    assert version.error_code == job["error_code"] == REASON_SOURCE_CHANGED
    assert job["status"] == JobStatus.FAILED.value
    assert db_session.query(SourceChunk).filter_by(version_id=version_id).count() == 0
    assert db_session.query(ChunkSearchIndex).count() == 0
    assert not db_session.query(Job).filter_by(
        version_id=version_id, job_type=RootJobType.EMBED_FILE.value
    ).count()
    files = client.get("/files", params={"root_id": root_id}).json()
    assert len(files) == 1
    assert (files[0]["status"], files[0]["error_code"]) == (
        VersionStatus.FAILED.value, REASON_SOURCE_CHANGED
    )

    source.write_bytes(original)
    assert client.post(f"/jobs/{extract_job.id}/retry").status_code == 202
    _run_next_job(db_session)
    db_session.expire_all()
    version = db_session.get(FileVersion, version_id)
    assert version.status == VersionStatus.BASIC_READY.value
    assert client.get(f"/jobs/{extract_job.id}").json()["attempts"] == 2
    chunk = db_session.query(SourceChunk).filter_by(version_id=version_id).one()
    assert chunk.text == original_text


def test_repeated_scans_after_success_create_nothing_new(client, corpus, db_session):
    """Idempotency after the happy path: no files, versions or live jobs added.

    Each ``POST /roots/{id}/scans`` legitimately adds one scan job - that is the
    endpoint's contract - but nothing it dispatches may duplicate: no new file
    rows, no new versions, no second extraction for the same version.
    """
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    worker_main.process_job(_extract_jobs(db_session, version.id)[0].id)

    db_session.expire_all()
    files_before = db_session.query(FileRecord).count()
    versions_before = db_session.query(FileVersion).count()
    chunks_before = db_session.query(SourceChunk).count()

    for _ in range(2):
        worker_main.process_job(_scan_and_collect(db_session, client, root_id))

    assert db_session.query(FileRecord).count() == files_before
    assert db_session.query(FileVersion).count() == versions_before
    assert db_session.query(SourceChunk).count() == chunks_before
    # One extraction was ever queued for this version, and it is finished.
    assert len(_extract_jobs(db_session, version.id)) == 1
    # The only live work is the single search-index job queued once.
    open_jobs = _open_jobs(db_session)
    assert [job.job_type for job in open_jobs] == [RootJobType.EMBED_FILE.value]


def test_a_file_removed_after_a_scan_is_listed_as_missing_with_a_reason(
    client, corpus, db_session
):
    """A1 over HTTP: the row explains itself instead of silently staying present."""
    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    version = _version_of(db_session, _only_file(db_session))
    worker_main.process_job(_extract_jobs(db_session, version.id)[0].id)

    (corpus / DOCUMENT).unlink()
    worker_main.process_job(_scan_and_collect(db_session, client, root_id))

    # The worker writes through its own session; drop the cached rows so the
    # API read reflects what it committed.
    db_session.expire_all()
    files = client.get("/files", params={"root_id": root_id}).json()
    assert len(files) == 1
    item = files[0]
    assert item["presence_status"] == "missing"
    assert item["presence_reason"] == REASON_FILE_MISSING
    # The indexed text is still described by its version; it is just not current.
    assert item["status"] == VersionStatus.BASIC_READY.value
    assert item["version_id"] == version.id


def test_a_directory_that_cannot_be_listed_keeps_its_files_unavailable(
    client, corpus, db_session, monkeypatch
):
    """A1 over HTTP: "we could not look inside" must not read as "deleted".

    The file is still on disk and still indexed; only the scan lost sight of its
    directory. Reporting `missing` would send the user looking for a deleted file.
    """
    (corpus / "locked").mkdir()
    shutil.copyfile(FIXTURE_PDF, corpus / "locked" / "nested.pdf")

    root_id, scan_job_id = _authorize(client)
    worker_main.process_job(scan_job_id)
    while (job := worker_main.claim_next_pending_job(db_session)) is not None:
        worker_main.process_job(job.job_id, job)

    db_session.expire_all()
    rows = {item["relative_path"]: item for item in client.get(
        "/files", params={"root_id": root_id}
    ).json()}
    assert set(rows) == {"lecture.pdf", "locked/nested.pdf"}
    assert all(item["status"] == VersionStatus.BASIC_READY.value for item in rows.values())

    real_scandir = os.scandir

    def failing_scandir(path="."):
        if Path(path).name == "locked":
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(scan_handler.os, "scandir", failing_scandir)
    worker_main.process_job(_scan_and_collect(db_session, client, root_id))

    db_session.expire_all()
    rows = {item["relative_path"]: item for item in client.get(
        "/files", params={"root_id": root_id}
    ).json()}
    nested = rows["locked/nested.pdf"]
    assert nested["presence_status"] == "unavailable"
    assert nested["presence_reason"] == "unreadable"
    # The indexed text is untouched: the version is still usable, just not current.
    assert nested["status"] == VersionStatus.BASIC_READY.value
    assert rows["lecture.pdf"]["presence_status"] == "present"


def test_an_unreadable_file_is_listed_as_unavailable_with_its_reason(
    client, corpus, db_session, monkeypatch
):
    """A1 over HTTP: "unreadable" is not "missing", and both are legible."""
    from services.parsing.pdf import REASON_UNREADABLE, SourceMissing

    root_id, scan_job_id = _authorize(client)
    real_identity = scan_handler.file_identity

    def flaky_identity(path):
        raise SourceMissing(REASON_UNREADABLE, "permission denied")

    monkeypatch.setattr(scan_handler, "file_identity", flaky_identity)
    worker_main.process_job(scan_job_id)
    monkeypatch.setattr(scan_handler, "file_identity", real_identity)

    files = client.get("/files", params={"root_id": root_id}).json()
    assert len(files) == 1
    assert files[0]["presence_status"] == "unavailable"
    assert files[0]["presence_reason"] == REASON_UNREADABLE
    # Nothing was read, so the file has no version and queued no job.
    assert files[0]["version_id"] is None
    assert db_session.query(FileVersion).count() == 0
    assert db_session.query(Job).count() == 1  # only the scan job itself
