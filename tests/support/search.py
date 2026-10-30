"""Materialize source bytes for search fixture versions.

Search tests historically inserted chunks directly. Evidence reads now require
the canonical current version to still match real bytes under its authorized
mount, so the import adapter's database rows need a matching test source file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.models import (
    AuthorizedRoot,
    FileRecord,
    FileVersion,
    SourceChunk,
)


def materialize_search_source(db: Session, version: FileVersion) -> Path:
    """Write deterministic bytes and bind the version to their content identity."""
    record = db.get(FileRecord, version.file_id)
    if record is None:
        raise AssertionError("search fixture has no file record")
    root = db.get(AuthorizedRoot, record.root_id)
    if root is None:
        raise AssertionError("search fixture has no authorized root")
    mounts = get_settings().source_mounts
    if root.mount_id not in mounts:
        raise AssertionError(f"test source mount {root.mount_id!r} is not configured")

    mount = Path(mounts[root.mount_id])
    root_dir = mount if root.relative_path == "." else mount / root.relative_path
    source_path = root_dir / record.relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = db.execute(
        select(SourceChunk)
        .where(SourceChunk.version_id == version.id)
        .order_by(SourceChunk.ordinal)
    ).scalars().all()
    payload = "\n".join(
        f"{chunk.ordinal}:{chunk.page_number}:{chunk.text}" for chunk in chunks
    ).encode("utf-8")
    source_path.write_bytes(payload)
    version.content_sha256 = hashlib.sha256(payload).hexdigest()
    version.byte_size = len(payload)
    db.flush()
    return source_path
