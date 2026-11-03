"""Queue missing current-source vectors after local model preparation succeeds.

This is a worker operation, not a search-time write or an extraction retry.
The caller owns the transaction and readiness polling; parsed source text and
all previously published vectors remain unchanged until the normal embed job
atomically publishes its replacement vectors.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AuthorizedRoot,
    FilePresence,
    FileRecord,
    FileVersion,
    Job,
    JobStatus,
    RootJobType,
    RootStatus,
    SourceChunk,
    VersionStatus,
)
from services.parsing.evidence import SourceUnavailable, readable_version_source
from services.scan.handler import MountNotAllowed, PathEscapesRoot, resolve_source_path
from services.search.token_store import (
    ChunkTokenIndex,
    index_matches_text,
    token_index_available,
)


def queue_startup_embeddings(db: Session) -> int:
    """Queue at most one live embed job per eligible incomplete version.

    PostgreSQL version-row locks serialize recovery workers and the ordinary
    extract-to-embed dispatcher. SQLite ignores FOR UPDATE and remains the
    single-worker development/test path. No new schema or source file writes
    occur here; missing C schema is a deployment problem, not a reason to create
    tables inside a poll. Paused roots remain readable but may not receive jobs.
    """
    db.flush()
    if not token_index_available(db):
        return 0
    versions = list(db.scalars(
        select(FileVersion)
        .join(FileRecord, FileRecord.current_version_id == FileVersion.id)
        .join(AuthorizedRoot, AuthorizedRoot.id == FileRecord.root_id)
        .where(
            FileVersion.file_id == FileRecord.id,
            AuthorizedRoot.status == RootStatus.ACTIVE.value,
            FileRecord.presence_status == FilePresence.PRESENT.value,
            FileVersion.status.in_([
                VersionStatus.BASIC_READY.value, VersionStatus.ENRICHED.value,
            ]),
            select(SourceChunk.id).where(SourceChunk.version_id == FileVersion.id).exists(),
        )
        .order_by(FileVersion.id)
        .with_for_update(of=FileVersion, skip_locked=True)
    ))
    queued = 0
    for version in versions:
        live_job = db.scalar(select(Job.id).where(
            Job.version_id == version.id,
            Job.job_type == RootJobType.EMBED_FILE.value,
            Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
        ).limit(1))
        if live_job is not None:
            continue
        chunks = db.execute(
            select(SourceChunk, ChunkTokenIndex)
            .outerjoin(ChunkTokenIndex, ChunkTokenIndex.chunk_id == SourceChunk.id)
            .where(SourceChunk.version_id == version.id)
        ).all()
        if not chunks or all(index_matches_text(index, chunk.text) for chunk, index in chunks):
            continue
        try:
            # New jobs require ACTIVE authorization, not the more permissive
            # read/evidence rules for paused roots. Verify real source identity
            # too: a stale database presence flag cannot authorize changed bytes.
            resolve_source_path(db, version.id, for_write=True)
            readable_version_source(db, version.id)
        except (SourceUnavailable, MountNotAllowed, PathEscapesRoot, LookupError, OSError):
            continue
        db.add(Job(
            version_id=version.id, job_type=RootJobType.EMBED_FILE.value,
            status=JobStatus.PENDING.value,
        ))
        queued += 1
    db.flush()  # Caller commits/rolls back; a repeated call sees the live jobs.
    return queued
