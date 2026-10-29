"""Resolve frozen aliases using authorized roots, full paths and content hashes."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    ChunkSearchIndex,
    FileRecord,
    FileVersion,
    SourceChunk,
)
from services.search.text import DIMENSIONS, MODEL_ID, normalize_text

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        return None
    return value


def expected_locations(query: dict) -> list[dict]:
    """Copy locations without rewriting the frozen input to bind runtime IDs."""
    if "expected" in query:
        values = query["expected"]
        if not isinstance(values, list) or not values or not all(
            isinstance(item, dict) for item in values
        ):
            raise ValueError("expected must be a nonempty array of source locations")
        return [dict(item) for item in values]
    return [{"file_id": query["expected_file_id"], "page": query["expected_page"]}]


def resolve_expected(
    db: Session,
    expected: dict,
    *,
    team_format: bool,
    manifest: dict | None,
    root_id: str | None,
) -> dict:
    """Resolve one acceptable answer, retaining failed-readiness diagnostics.

    The team gold's IDs are manifest aliases, never database IDs. No basename
    matching or historical-version substitution is permitted.
    """
    result = {
        "expected": dict(expected),
        "mapping_method": "root_relative_path_sha256" if team_format else "legacy_explicit_id",
        "root_id": root_id,
        "file_id": None,
        "version_id": None,
        "relative_path": None,
        "content_sha256": None,
        "page": expected.get("page"),
        "ready": False,
        "keyword_ready": False,
        "semantic_ready": False,
        "diagnostics": [],
        "semantic_diagnostics": [],
    }

    def fail(code: str, reason: str, **details) -> dict:
        result["diagnostics"].append({"code": code, "reason": reason, **details})
        return result

    manifest_record = None
    if team_format:
        if root_id is None:
            return fail("root_scope_required", "Provide the scanned authorized root UUID")
        if manifest is None:
            return fail("corpus_manifest_required", "Team aliases require the frozen manifest")
        path = _relative_path(expected.get("relative_path"))
        if path is None:
            return fail("corpus_mismatch", "Expected path must be a complete relative POSIX path")
        records = [item for item in manifest.get("files", []) if item.get("relative_path") == path]
        if len(records) != 1:
            return fail(
                "corpus_mismatch", "Expected path is absent or ambiguous in the manifest",
                relative_path=path, manifest_matches=len(records),
            )
        manifest_record = records[0]
        if expected.get("file_id") != manifest_record.get("file_id"):
            return fail("corpus_mismatch", "Frozen file alias disagrees with manifest path")
        if expected.get("version_id") != manifest_record.get("version_id"):
            return fail("version_mismatch", "Frozen version alias disagrees with manifest")
        identity = manifest_record.get("sha256", "")
        if not isinstance(identity, str) or not _SHA256.fullmatch(identity):
            return fail("corpus_mismatch", "Manifest has no valid SHA-256 content identity")
        for field in ("sha256", "content_sha256"):
            if field in expected and expected[field] != identity:
                return fail("version_mismatch", "Frozen answer hash disagrees with manifest")
        result.update(relative_path=path, content_sha256=identity)
        root = db.get(AuthorizedRoot, root_id)
        if root is None:
            return fail("corpus_mismatch", "The requested scanned root does not exist")
        if root.status not in {"active", "paused"}:
            return fail(
                "root_not_authorized", "The requested root is not readable", status=root.status,
            )
        result["root_scope"] = {
            "root_id": root.id, "mount_id": root.mount_id, "relative_path": root.relative_path,
        }
        file_record = db.scalar(
            select(FileRecord).where(
                FileRecord.root_id == root_id, FileRecord.relative_path == path,
            )
        )
    else:
        file_record = db.get(FileRecord, expected.get("file_id"))
        if file_record is not None and root_id is not None and file_record.root_id != root_id:
            return fail("corpus_mismatch", "Legacy file ID is outside the requested root")

    if file_record is None:
        return fail("corpus_mismatch", "No scanned file at the expected root and relative path")
    result.update(
        root_id=file_record.root_id,
        file_id=file_record.id,
        relative_path=file_record.relative_path,
    )
    if file_record.presence_status != "present":
        return fail(
            "file_missing", "Expected scanned file is not present",
            status=file_record.presence_status,
        )
    root = db.get(AuthorizedRoot, file_record.root_id)
    if root is None or root.status not in {"active", "paused"}:
        return fail("root_not_authorized", "Expected file's root is not readable")
    current = (
        db.get(FileVersion, file_record.current_version_id)
        if file_record.current_version_id else None
    )
    if current is None or current.file_id != file_record.id:
        return fail("version_mismatch", "Expected file has no valid current version")
    result["version_id"] = current.id
    if team_format and current.content_sha256 != result["content_sha256"]:
        historical = db.scalar(select(FileVersion.id).where(
            FileVersion.file_id == file_record.id,
            FileVersion.content_sha256 == result["content_sha256"],
        ))
        return fail(
            "version_mismatch", "Current scanned content differs from the frozen corpus",
            current_sha256=current.content_sha256, historical_version_id=historical,
        )
    result["content_sha256"] = current.content_sha256
    result["parser_revision"] = current.parser_revision
    if current.status not in {"basic_ready", "enriched"}:
        return fail(
            "index_not_ready", "Source version has not reached a searchable state",
            version_status=current.status, version_error=current.error_code,
        )
    page = expected.get("page")
    if type(page) is not int or page < 1:
        return fail("expected_page_missing", "Expected PDF page must be a positive integer")
    if manifest_record is not None and page > manifest_record.get("page_count", 0):
        return fail("expected_page_missing", "Expected page exceeds the frozen PDF page count")
    chunks = list(db.scalars(select(SourceChunk).where(SourceChunk.version_id == current.id)))
    page_chunks = [chunk for chunk in chunks if chunk.page_number == page]
    if not page_chunks:
        return fail(
            "expected_page_missing", "No parsed source chunk exists on the expected page",
            parsed_pages=sorted({
                chunk.page_number for chunk in chunks if chunk.page_number is not None
            }),
        )
    if expected.get("excerpt") and not any(
        normalize_text(expected["excerpt"]) in normalize_text(chunk.text) for chunk in page_chunks
    ):
        return fail("corpus_mismatch", "Frozen excerpt is absent from the expected parsed page")
    indexes = list(db.scalars(select(ChunkSearchIndex).where(
        ChunkSearchIndex.chunk_id.in_([chunk.id for chunk in chunks])
    )))
    result["chunk_count"] = len(chunks)
    result["indexed_chunk_count"] = len(indexes)
    if len(indexes) != len(chunks) or any(not item.search_text for item in indexes):
        return fail("index_not_ready", "Keyword sidecars are missing or empty")
    result["keyword_ready"] = result["ready"] = True
    compatible = sum(
        item.embedding is not None
        and item.embedding_model == MODEL_ID
        and item.embedding_dimensions == DIMENSIONS
        for item in indexes
    )
    result["compatible_vector_count"] = compatible
    result["semantic_ready"] = compatible == len(chunks)
    if not result["semantic_ready"]:
        result["semantic_diagnostics"].append({
            "code": "index_not_ready",
            "reason": "Some source chunks have no compatible vector for the frozen model",
            "channel": "semantic",
            "compatible_vector_count": compatible,
            "chunk_count": len(chunks),
        })
    return result
