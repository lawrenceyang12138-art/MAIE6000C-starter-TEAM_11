"""The team benchmark must pass through the real PDF ingestion handlers."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select

from scripts.evaluate_team_pdf import (
    CorpusValidationError,
    evaluate_corpus,
    public_command,
    stage_corpus,
    validate_corpus,
    validate_report_destination,
)
from services.common.config import Settings
from services.common.models import ChunkSearchIndex, FileRecord, SourceChunk
from services.parsing.evidence import read_evidence
from services.search.text import (
    MAX_DOCUMENT_MODEL_TOKENS,
    MAX_QUERY_MODEL_TOKENS,
    MODEL_ID,
    TOKEN_DIMENSIONS,
)
from services.search.token_store import ChunkTokenIndex

REPO = Path(__file__).resolve().parents[2]


def _manifest():
    return json.loads((REPO / "fixtures/manifest.json").read_text(encoding="utf-8"))


def test_team_pdf_scan_parse_index_uses_real_uuids_and_source_evidence(db_session, tmp_path):
    manifest = _manifest()
    gold = json.loads((REPO / "submissions/week07/gold-queries.json").read_text(encoding="utf-8"))
    corpus = tmp_path / "corpus"
    before = stage_corpus(REPO / "fixtures", corpus, manifest)
    report = evaluate_corpus(
        db_session, corpus, gold, manifest, Settings(embedding_enabled=False, _env_file=None), None
    )
    assert report["pipeline"]["scan"]["files_created"] == 16
    assert report["pipeline"]["parsed_files_this_run"] == 16
    assert report["pipeline"]["search_index_chunks"] == 20
    assert report["pipeline"]["compatible_token_index_chunks"] == 0
    assert report["pipeline"]["token_vector_count"] == 0
    assert report["pipeline"]["status_counts"]["basic_ready"] == 12
    assert report["source_bytes_unchanged"]
    assert validate_corpus(corpus, manifest) == before
    assert report["summary"]["keyword_top1"] == "5/5"
    assert report["summary"]["semantic_top3"] == "0/5"
    assert not report["passed"]
    assert UUID(report["pipeline"]["root_id"])
    for source in report["pipeline"]["files"]:
        assert UUID(source["file_id"]) and UUID(source["version_id"])
    for chunk in db_session.scalars(select(SourceChunk)):
        evidence = read_evidence(db_session, chunk.id)
        assert UUID(evidence.chunk_id)
        assert evidence.version_id == chunk.version_id
        assert evidence.page_number == chunk.page_number
        assert evidence.text == chunk.text
    original_chunks = {
        (chunk.version_id, chunk.ordinal): chunk.id
        for chunk in db_session.scalars(select(SourceChunk))
    }
    repeated = evaluate_corpus(
        db_session, corpus, gold, manifest, Settings(embedding_enabled=False, _env_file=None), None
    )
    assert repeated["pipeline"]["root_id"] == report["pipeline"]["root_id"]
    assert repeated["pipeline"]["scan"]["files_created"] == 0
    assert repeated["pipeline"]["scan"]["versions_created"] == 0
    assert repeated["pipeline"]["parsed_files_this_run"] == 16
    assert {
        (chunk.version_id, chunk.ordinal): chunk.id
        for chunk in db_session.scalars(select(SourceChunk))
    } == original_chunks
    assert db_session.scalar(select(func.count()).select_from(SourceChunk)) == 20
    assert db_session.scalar(select(func.count()).select_from(ChunkSearchIndex)) == 20


def test_reused_database_reparses_pdf_instead_of_hand_authored_chunks(db_session, tmp_path):
    manifest = _manifest()
    gold = json.loads((REPO / "submissions/week07/gold-queries.json").read_text(encoding="utf-8"))
    corpus = tmp_path / "corpus"
    stage_corpus(REPO / "fixtures", corpus, manifest)
    settings = Settings(embedding_enabled=False, _env_file=None)
    evaluate_corpus(db_session, corpus, gold, manifest, settings, None)
    source = db_session.scalar(select(SourceChunk).order_by(SourceChunk.id))
    original = (source.version_id, source.ordinal, source.text)
    source.text += "\nFabricated hand-authored benchmark passage."
    db_session.commit()
    report = evaluate_corpus(db_session, corpus, gold, manifest, settings, None)
    restored = db_session.scalar(select(SourceChunk).where(
        SourceChunk.version_id == original[0], SourceChunk.ordinal == original[1]
    ))
    assert restored.text == original[2]
    assert report["pipeline"]["parsed_files_this_run"] == 16
    assert report["summary"]["keyword_top1"] == "5/5"


def test_reused_database_with_other_corpus_paths_is_diagnosed_without_silent_filtering(
    db_session, tmp_path
):
    manifest = _manifest()
    gold = json.loads((REPO / "submissions/week07/gold-queries.json").read_text(encoding="utf-8"))
    corpus = tmp_path / "corpus"
    stage_corpus(REPO / "fixtures", corpus, manifest)
    settings = Settings(embedding_enabled=False, _env_file=None)
    initial = evaluate_corpus(db_session, corpus, gold, manifest, settings, None)
    db_session.add(FileRecord(
        root_id=initial["pipeline"]["root_id"], relative_path="legacy/obsolete.pdf",
        name="obsolete.pdf", presence_status="present",
    ))
    db_session.commit()
    with pytest.raises(CorpusValidationError) as failure:
        evaluate_corpus(db_session, corpus, gold, manifest, settings, None)
    assert failure.value.diagnostics == [{
        "code": "database_corpus_mismatch",
        "extra_relative_paths": ["legacy/obsolete.pdf"], "missing_relative_paths": [],
    }]


def test_manifest_subset_staging_never_scans_legacy_search_and_b_corpora(tmp_path):
    manifest = _manifest()
    target = tmp_path / "corpus"
    files = stage_corpus(REPO / "fixtures", target, manifest)
    assert len(files) == 16
    actual_paths = {
        item.relative_to(target).as_posix() for item in target.rglob("*") if item.is_file()
    }
    assert actual_paths == {record["relative_path"] for record in manifest["files"]}


def test_corpus_byte_mismatch_is_explicit_and_cannot_overwrite_a_prior_stage(tmp_path):
    manifest = _manifest()
    target = tmp_path / "corpus"
    stage_corpus(REPO / "fixtures", target, manifest)
    changed = target / manifest["files"][0]["relative_path"]
    changed.write_bytes(b"changed content")
    with pytest.raises(CorpusValidationError) as failure:
        stage_corpus(REPO / "fixtures", target, manifest)
    assert failure.value.diagnostics[0]["code"] == "corpus_content_mismatch"
    assert changed.read_bytes() == b"changed content"


def test_unexpected_files_and_manifest_path_escape_are_rejected(tmp_path):
    manifest = _manifest()
    target = tmp_path / "corpus"
    stage_corpus(REPO / "fixtures", target, manifest)
    (target / "unrelated.pdf").write_bytes(b"unrelated")
    with pytest.raises(CorpusValidationError) as failure:
        validate_corpus(target, manifest)
    assert failure.value.diagnostics == [
        {"code": "corpus_unexpected_files", "relative_paths": ["unrelated.pdf"]}
    ]
    manifest["files"][0]["relative_path"] = "../outside.pdf"
    with pytest.raises(CorpusValidationError) as failure:
        validate_corpus(target, manifest)
    assert failure.value.diagnostics[0]["code"] == "path_out_of_scope"


def test_shared_command_records_redact_passwords_with_both_cli_argument_forms():
    connection = "postgresql+psycopg://operator:private-demo-password@localhost:15432/demo"
    for arguments in (["--database-url", connection], ["--database-url=" + connection]):
        original = ["python", "-m", "scripts.evaluate_team_pdf", *arguments, "--backend", "off"]
        recorded = public_command(original)
        assert "private-demo-password" not in " ".join(recorded)
        assert "operator:***@localhost:15432/demo" in " ".join(recorded)
        assert "private-demo-password" in " ".join(original)


def test_actual_cli_initializes_sqlite_and_reports_migration_limitations(tmp_path):
    output = tmp_path / "report.json"
    arguments = [
        sys.executable, "-m", "scripts.evaluate_team_pdf",
        "--database-url", f"sqlite:///{tmp_path / 'cli.db'}",
        "--stage-dir", str(tmp_path / "corpus"),
        "--backend", "off", "--output", str(output),
    ]
    completed = subprocess.run(
        arguments, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        check=False, timeout=60,
    )
    assert completed.returncode == 1, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "evaluated"
    assert report["database"]["schema_source"] == "sqlalchemy_metadata_sqlite_test_only"
    assert report["database"]["schema_action"] == "created_empty_database"
    assert report["database"]["pg_only_migration_validation"] is False
    assert report["database"]["token_schema_source"] == "c_owned_prepare_search_schema"
    assert report["configuration"]["model"] == MODEL_ID
    assert report["configuration"]["dimensions"] == TOKEN_DIMENSIONS
    assert report["configuration"]["representation"] == "token_multivector"
    assert report["configuration"]["scoring"] == "maxsim_mean"
    assert report["configuration"]["pooling"] == "none_token_vectors_retained"
    assert report["configuration"]["query_prefix"] == "[Q] "
    assert report["configuration"]["passage_prefix"] == "[D] "
    assert report["configuration"]["maximum_query_model_tokens"] == MAX_QUERY_MODEL_TOKENS
    assert report["configuration"]["maximum_document_model_tokens"] == MAX_DOCUMENT_MODEL_TOKENS
    assert report["pipeline"]["parsed_files_this_run"] == 16
    assert report["pipeline"]["search_index_chunks"] == 20
    assert report["summary"]["keyword_top1"] == "5/5"
    assert report["summary"]["semantic_top3"] == "0/5"
    # Exit 1 represents the deliberately unmet semantic gate with AI disabled.
    assert not report["passed"]
    # An existing canonical database can acquire C's new derived table without
    # pretending that an A-owned canonical migration has changed.
    with sqlite3.connect(tmp_path / "cli.db") as connection:
        connection.execute(f'DROP TABLE "{ChunkTokenIndex.__tablename__}"')
    repeated = subprocess.run(
        arguments, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        check=False, timeout=60,
    )
    assert repeated.returncode == 1, repeated.stderr
    after = json.loads(output.read_text(encoding="utf-8"))
    assert after["database"]["schema_action"] == "validated_existing_metadata_schema"
    assert after["pipeline"]["root_id"] == report["pipeline"]["root_id"]
    with sqlite3.connect(tmp_path / "cli.db") as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
            (ChunkTokenIndex.__tablename__,),
        ).fetchone()[0] == 1


def test_actual_cli_refuses_partial_sqlite_without_repairing_it(tmp_path):
    database = tmp_path / "partial.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE cases (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO cases VALUES ('preserve-this-row')")
    original_bytes = database.read_bytes()
    output = tmp_path / "partial-report.json"
    completed = subprocess.run([
        sys.executable, "-m", "scripts.evaluate_team_pdf",
        "--database-url", f"sqlite:///{database}",
        "--stage-dir", str(tmp_path / "corpus"),
        "--backend", "off", "--output", str(output),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=60)
    assert completed.returncode == 1, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "preflight_failed"
    assert report["diagnostics"][0]["code"] == "sqlite_schema_partial"
    assert report["diagnostics"][0]["action"] == "refused_without_modifying_existing_schema"
    assert database.read_bytes() == original_bytes


def test_report_destination_guard_protects_each_frozen_input_and_resolved_alias(tmp_path):
    inputs = [tmp_path / name for name in ("gold.json", "manifest.json", "freeze.json")]
    for source in inputs:
        source.write_bytes(b"immutable frozen input")
        alias = source.parent / "." / source.name
        with pytest.raises(ValueError, match="output_path_conflict"):
            validate_report_destination(alias, protected_files=inputs, source_directories=[])
        assert source.read_bytes() == b"immutable frozen input"
    validate_report_destination(
        tmp_path / "reports/result.json", protected_files=inputs,
        source_directories=[tmp_path / "sources"],
    )


@pytest.mark.parametrize("collision", ["gold", "fixture_pdf", "stage_pdf", "corpus_directory"])
def test_actual_cli_refuses_output_collisions_before_touching_inputs(tmp_path, collision):
    gold = tmp_path / "gold.json"
    fixture_root = tmp_path / "fixtures"
    stage_dir = tmp_path / "staged"
    corpus_dir = tmp_path / "existing-corpus"
    original = b"Original input bytes must not be overwritten by a report."
    gold.write_bytes(original)
    fixture_root.mkdir()
    stage_dir.mkdir()
    corpus_dir.mkdir()
    if collision == "gold":
        output = gold.parent / "." / gold.name
    elif collision == "fixture_pdf":
        output = fixture_root / "original.pdf"
        output.write_bytes(original)
    elif collision == "stage_pdf":
        output = stage_dir / "original.pdf"
        output.write_bytes(original)
    else:
        output = corpus_dir
    database = tmp_path / "must-not-be-created.db"
    completed = subprocess.run([
        sys.executable, "-m", "scripts.evaluate_team_pdf",
        "--database-url", f"sqlite:///{database}", "--backend", "off",
        "--gold", str(gold), "--fixture-root", str(fixture_root),
        "--stage-dir", str(stage_dir), "--corpus-dir", str(corpus_dir),
        "--output", str(output),
    ], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False, timeout=60)
    assert completed.returncode == 2
    assert "output_path_" in completed.stderr
    assert not database.exists()
    assert gold.read_bytes() == original
    if output.is_file():
        assert output.read_bytes() == original
    else:
        assert list(output.iterdir()) == []
