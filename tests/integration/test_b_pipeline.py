"""Clean-database scans through B's parsing and relation pipeline."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.schemas import SearchRequest
from services.common.models import (
    AuthorizedRoot,
    Entity,
    FileRecord,
    FileVersion,
    RootStatus,
    VersionStatus,
)
from services.parsing.evidence import read_evidence
from services.parsing.graph import read_relationships
from services.parsing.handler import handle_extract_file
from services.parsing.text import TextParsingPolicy
from services.search.retrieval import search_chunks
from services.scan.handler import handle_scan_root, resolve_source_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _mount_source(db: Session, monkeypatch, tmp_path: Path) -> Path:
    source_root = tmp_path / "source"
    source_root.mkdir()
    monkeypatch.setattr(
        get_settings(),
        "source_mounts",
        {"corpus": str(source_root)},
    )
    return source_root


def _extract_scanned_root(db: Session, root: AuthorizedRoot) -> list[FileVersion]:
    summary = handle_scan_root(db, root.id)
    versions = db.execute(
        select(FileVersion)
        .join(FileRecord, FileRecord.id == FileVersion.file_id)
        .where(FileRecord.root_id == root.id)
        .order_by(FileRecord.relative_path)
    ).scalars().all()
    assert summary["files_seen"] == len(versions)
    assert summary["jobs_dispatched"] == len(versions)

    for version in versions:
        source_path = resolve_source_path(db, version.id)
        handle_extract_file(db, version.id, source_path)
    db.expire_all()
    return versions


def test_clean_scan_produces_the_expected_team_corpus_outcomes(
    db_session: Session, monkeypatch, tmp_path: Path
):
    source_root = _mount_source(db_session, monkeypatch, tmp_path)
    corpus = source_root / "corpus"
    shutil.copytree(FIXTURES / "regression", corpus / "regression")
    abnormal = corpus / "abnormal"
    abnormal.mkdir()
    for name in ("corrupt.pdf", "encrypted.pdf", "no_text_layer.pdf"):
        shutil.copyfile(FIXTURES / "parsing" / name, abnormal / name)

    root = AuthorizedRoot(
        mount_id="corpus",
        relative_path="corpus",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(root)
    db_session.commit()

    versions = _extract_scanned_root(db_session, root)

    assert len(versions) == 16
    statuses = [version.status for version in versions]
    assert statuses.count(VersionStatus.BASIC_READY.value) == 12
    assert statuses.count(VersionStatus.UNSUPPORTED.value) == 4
    unsupported = {
        db_session.get(FileRecord, version.file_id).name: version.error_code
        for version in versions
        if version.status == VersionStatus.UNSUPPORTED.value
    }
    assert unsupported == {
        "corrupt.pdf": "corrupt",
        "encrypted.pdf": "encrypted",
        "no_text_layer.pdf": "no_text_layer",
        "unsupported.txt": "unsupported_format",
    }


def test_clean_scan_automatically_persists_direct_relation_evidence(
    db_session: Session, monkeypatch, tmp_path: Path
):
    source_root = _mount_source(db_session, monkeypatch, tmp_path)
    relations_source = source_root / "relations"
    relations_source.mkdir()
    shutil.copyfile(
        FIXTURES / "relations" / "entities.pdf",
        relations_source / "entities.pdf",
    )
    root = AuthorizedRoot(
        mount_id="corpus",
        relative_path="relations",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(root)
    db_session.commit()

    versions = _extract_scanned_root(db_session, root)

    assert len(versions) == 1
    version = versions[0]
    assert version.status == VersionStatus.BASIC_READY.value
    entities = db_session.execute(select(Entity)).scalars().all()
    assert {"person", "project", "topic"} <= {entity.entity_type for entity in entities}

    relations = read_relationships(db_session, version.id)
    assert relations
    for relation in relations:
        assert relation.chunk_id is not None
        evidence = read_evidence(db_session, relation.chunk_id)
        assert evidence.version_id == version.id
        assert evidence.page_number == relation.page_number
        assert relation.quote.split()[0].casefold() in evidence.text.casefold()


@pytest.mark.parametrize(
    ("word_namespace", "relationship_base"),
    [
        (
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        ),
        (
            "http://purl.oclc.org/ooxml/wordprocessingml/main",
            "http://purl.oclc.org/ooxml/officeDocument/relationships",
        ),
    ],
    ids=["transitional-docx", "strict-docx"],
)
def test_fresh_text_formats_flow_from_scan_to_search_and_evidence(
    db_session: Session, monkeypatch, tmp_path: Path, word_namespace, relationship_base
):
    source_root = _mount_source(db_session, monkeypatch, tmp_path)
    corpus = source_root / "text-corpus"
    corpus.mkdir()
    txt_text = "database-\nready\n    indented note\n"
    markdown_text = "# Markdown\n\n    publish example\n"
    docx_text = "Quarterly\nplanning\tpassage"
    (corpus / "notes.txt").write_text(txt_text, encoding="utf-8")
    (corpus / "notes.md").write_text(markdown_text, encoding="utf-8")
    docx = corpus / "notes.docx"
    with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" '
            f'Type="{relationship_base}/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{word_namespace}"><w:body><w:p>'
            '<w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
            "<w:r><w:t>Quarterly</w:t><w:cr/><w:t>planning</w:t>"
            "<w:tab/><w:t>passage</w:t></w:r></w:p></w:body></w:document>",
        )

    root = AuthorizedRoot(
        mount_id="corpus",
        relative_path="text-corpus",
        status=RootStatus.ACTIVE.value,
    )
    db_session.add(root)
    db_session.commit()
    summary = handle_scan_root(db_session, root.id)
    versions = db_session.execute(
        select(FileVersion)
        .join(FileRecord, FileRecord.id == FileVersion.file_id)
        .where(FileRecord.root_id == root.id)
    ).scalars().all()
    assert summary["files_seen"] == len(versions) == 3

    policy = TextParsingPolicy(enabled=True, docx_enabled=True)
    for version in versions:
        source_path = resolve_source_path(db_session, version.id)
        assert (
            handle_extract_file(
                db_session,
                version.id,
                source_path,
                text_policy=policy,
            )
            == VersionStatus.BASIC_READY.value
        )

    settings = get_settings()
    for query, file_name, passage in (
        ("ready", "notes.txt", txt_text),
        ("publish", "notes.md", markdown_text),
        ("planning", "notes.docx", docx_text),
    ):
        result = search_chunks(
            db_session,
            SearchRequest(query=query, mode="keyword", root_id=root.id),
            settings,
            None,
        )
        assert len(result.results) == 1, query
        (hit,) = result.results
        assert hit.file_name == file_name
        assert hit.page is None
        assert hit.text == passage
        evidence = read_evidence(db_session, hit.chunk_id)
        assert evidence.chunk_id == hit.chunk_id
        assert evidence.file_id == hit.file_id
        assert evidence.version_id == hit.version_id
        assert evidence.relative_path == hit.file_path == file_name
        assert evidence.page_number is None
        assert evidence.ordinal == hit.ordinal == 1
        assert evidence.text == passage

    concatenated = search_chunks(
        db_session,
        SearchRequest(query="quarterlyplanning", mode="keyword", root_id=root.id),
        settings,
        None,
    )
    assert not concatenated.results
