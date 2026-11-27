"""The extraction handler the worker calls for one file version.

This is the seam between the worker's dispatch loop (owned by A) and the
parsing workstream (owned by B). The worker hands over a version id and a path;
this module decides the outcome and records it on the version.

Four things matter here:

1. **A bad document must not raise.** An encrypted, damaged, or image-only file
   is an ordinary result. It is recorded against the version and returns
   normally, so the worker can carry on with the next file instead of the whole
   scan stopping at the first problem.
2. **A file that changed while we read it must not be published.** Extraction
   produces a hash of what was actually read. If it differs from the hash the
   version was created with, the bytes on disk are no longer the version we
   were asked to process, so the chunks are discarded rather than stored
   against the wrong content. A parser rejection is tied to that same
   identity so a newer file cannot leave the original version unsupported.
   Before publishing native text or a terminal rejection, recheck the path in case it was
   replaced after the snapshot was taken.
3. **Relations are part of a successful parse.** Chunks, rule-based entity
   candidates, their source evidence and the `basic_ready` result commit
   together. An incomplete relation batch must not look like a usable document.
4. **Anything else propagates.** A database outage is not a property of the
   file, so it is not swallowed here; the worker decides how to retry.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from services.common.claim import StaleClaim
from services.common.models import FileVersion, VersionStatus
from services.parsing.chunking import chunk_document
from services.parsing.pdf import (
    REASON_SOURCE_CHANGED,
    SourceChanged,
    SourceMissing,
    UnsupportedDocument,
    extract_document,
    verify_source,
)
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations
from services.search.keyword_index import prepare_keyword_indexes

# Stamped onto every version this handler processes, so chunks can be traced
# back to the parser that produced them. Bump it when the parsing behaviour
# changes, otherwise a re-parse is indistinguishable from the first parse.
PARSER_REVISION = "parsing-v6"

# Recorded when the work itself fails rather than the document: a database
# error while storing, for instance. The version must not be left saying it is
# still being extracted.
REASON_PROCESSING_FAILED = "processing_failed"


def _commit_if_owned(db: Session, version_id: str, *, guard) -> None:
    """Commit a version write only while this attempt still owns the job.

    The guard locks the job row in the caller's transaction, so the check and
    the write it protects cannot be separated. ``guard`` is required: an omitted
    argument must not silently disable the check.
    """
    if guard is not None and not guard():
        db.rollback()
        raise StaleClaim(f"version {version_id} is no longer owned by this attempt")
    db.commit()


def _finish(
    db: Session,
    version_id: str,
    status: str,
    error_code: str | None,
    *,
    guard,
) -> str:
    version = db.get(FileVersion, version_id)
    if version is None:
        raise LookupError(f"file version {version_id} disappeared mid-processing")
    version.parser_revision = PARSER_REVISION
    version.status = status
    version.error_code = error_code
    _commit_if_owned(db, version_id, guard=guard)
    return status


def handle_extract_file(
    db: Session,
    version_id: str,
    source_path: str | Path,
    *,
    guard=None,
    text_policy=None,
) -> str:
    """Extract, chunk and store one file version.

    Returns the resulting version status. Raises only for conditions that are
    not properties of this document, or when the version does not exist.
    """
    version = db.get(FileVersion, version_id)
    if version is None:
        raise LookupError(f"unknown file version {version_id}")

    expected_sha256 = version.content_sha256
    expected_byte_size = version.byte_size

    # A worker can lose its claim between selecting this path and entering the
    # parser. Check before the first write and commit before the file read, so
    # the job-row lock never spans the slow part.
    version.status = VersionStatus.EXTRACTING.value
    version.error_code = None
    _commit_if_owned(db, version_id, guard=guard)

    try:
        # Keep the zero-argument call shape used by existing ownership tests and
        # by deployments whose parser wrapper does not know about text policy.
        try:
            if text_policy is None:
                document = extract_document(source_path)
            else:
                document = extract_document(source_path, text_policy=text_policy)
        except UnsupportedDocument as exc:
            if exc.content_sha256 is None or exc.content_sha256 != expected_sha256:
                raise SourceChanged(REASON_SOURCE_CHANGED, "Rejected a different version") from exc
            # Matching the scanned bytes alone says nothing about the path now.
            # Source errors here follow the same retry path as extraction errors.
            verify_source(source_path, content_sha256=expected_sha256, byte_size=expected_byte_size)
            return _finish(
                db, version_id, VersionStatus.UNSUPPORTED.value, exc.reason_code, guard=guard
            )

        if document.content_sha256 != expected_sha256:
            # The file changed underneath us. Publishing now would attach text
            # from one set of bytes to a version row that claims different ones.
            return _finish(
                db, version_id, VersionStatus.FAILED.value, REASON_SOURCE_CHANGED,
                guard=guard,
            )

        chunks = chunk_document(document)
        # Chunks, rule candidates and the final ready status form one
        # transaction. A relation persistence failure must not publish a
        # half-built parse that looks complete to the worker or API.
        persist_chunks(db, version_id, chunks, commit=False)
        # A basic_ready document must already be keyword-searchable. Publishing
        # this with the parse avoids an empty first search while a later embed
        # job is waiting for an unavailable or warming local model.
        prepare_keyword_indexes(db, version_id)
        # TXT/Markdown is intentionally a text-only slice. Relation candidates
        # remain a PDF feature until a separate text relation policy is approved.
        if document.source_kind == "pdf":
            persist_relations(
                db,
                version_id,
                candidate_relations(chunks),
                commit=False,
            )

        version = db.get(FileVersion, version_id)
        if version is None:
            raise LookupError(f"file version {version_id} disappeared mid-processing")
        version.parser_revision = PARSER_REVISION
        version.status = VersionStatus.BASIC_READY.value
        version.error_code = None
        if document.source_kind in {"text", "markdown", "docx"}:
            # Parsing uses a stable in-memory snapshot. The path can still be
            # atomically replaced while that snapshot is being read or decoded.
            # Recheck after staging rows but just before commit; on mismatch,
            # the failure handler rolls back all staged chunks and indexes.
            verify_source(
                source_path, content_sha256=expected_sha256, byte_size=expected_byte_size
            )
        # Chunks, relation candidates and the ready status publish only while
        # this attempt still owns the job: a stale parse would replace rows that
        # a newer attempt already published.
        _commit_if_owned(db, version_id, guard=guard)
    except (SourceMissing, SourceChanged) as exc:
        # Source access/change failures are retryable. Discard any staged
        # parse and indexes before committing the failure status.
        db.rollback()
        return _finish(
            db, version_id, VersionStatus.FAILED.value, exc.reason_code,
            guard=guard,
        )
    except StaleClaim:
        # The publish was refused because another attempt owns the job. Its
        # result stands; writing a failure here would overwrite it.
        raise
    except Exception:
        # Everything from here on runs after the row was committed as
        # "extracting". If any step fails - the reader, the chunker or the
        # store - leaving the row mid-extraction makes it indistinguishable
        # from one that is still running, so the outcome is recorded before the
        # error goes up for the worker to decide whether to retry. The rollback
        # ends the previous transaction, so the failure write checks ownership
        # again: a worker that lost the job must not report its own failure onto
        # the new owner's version.
        db.rollback()
        _finish(
            db, version_id, VersionStatus.FAILED.value, REASON_PROCESSING_FAILED,
            guard=guard,
        )
        raise

    return VersionStatus.BASIC_READY.value
