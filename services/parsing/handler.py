"""The extraction handler the worker calls for one file version.

This is the seam between the worker's dispatch loop (owned by A) and the
parsing workstream (owned by B). The worker hands over a version id and a path;
this module decides the outcome and records it on the version.

Three things matter here:

1. **A bad document must not raise.** An encrypted, damaged, or image-only file
   is an ordinary result. It is recorded against the version and returns
   normally, so the worker can carry on with the next file instead of the whole
   scan stopping at the first problem.
2. **A file that changed while we read it must not be published.** Extraction
   produces a hash of what was actually read. If it differs from the hash the
   version was created with, the bytes on disk are no longer the version we
   were asked to process, so the chunks are discarded rather than stored
   against the wrong content.
3. **Relations are part of a successful parse.** Chunks, rule-based entity
   candidates, their source evidence and the `basic_ready` result commit
   together. An incomplete relation batch must not look like a usable document.
4. **Anything else propagates.** A database outage is not a property of the
   file, so it is not swallowed here; the worker decides how to retry.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from services.common.models import FileVersion, VersionStatus
from services.parsing.chunking import chunk_document
from services.parsing.pdf import (
    REASON_SOURCE_CHANGED,
    SourceChanged,
    SourceMissing,
    UnsupportedDocument,
    extract_document,
)
from services.parsing.persist import persist_chunks, persist_relations
from services.parsing.relations import candidate_relations
from services.search.keyword_index import prepare_keyword_indexes

# Stamped onto every version this handler processes, so chunks can be traced
# back to the parser that produced them. Bump it when the parsing behaviour
# changes, otherwise a re-parse is indistinguishable from the first parse.
PARSER_REVISION = "parsing-v1"

# Recorded when the work itself fails rather than the document: a database
# error while storing, for instance. The version must not be left saying it is
# still being extracted.
REASON_PROCESSING_FAILED = "processing_failed"


def _finish(db: Session, version_id: str, status: str, error_code: str | None) -> str:
    version = db.get(FileVersion, version_id)
    if version is None:
        raise LookupError(f"file version {version_id} disappeared mid-processing")
    version.parser_revision = PARSER_REVISION
    version.status = status
    version.error_code = error_code
    db.commit()
    return status


def handle_extract_file(db: Session, version_id: str, source_path: str | Path) -> str:
    """Extract, chunk and store one file version.

    Returns the resulting version status. Raises only for conditions that are
    not properties of this document, or when the version does not exist.
    """
    version = db.get(FileVersion, version_id)
    if version is None:
        raise LookupError(f"unknown file version {version_id}")

    expected_sha256 = version.content_sha256

    version.status = VersionStatus.EXTRACTING.value
    version.error_code = None
    db.commit()

    try:
        document = extract_document(source_path)

        if document.content_sha256 != expected_sha256:
            # The file changed underneath us. Publishing now would attach text
            # from one set of bytes to a version row that claims different ones.
            return _finish(
                db, version_id, VersionStatus.FAILED.value, REASON_SOURCE_CHANGED
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
        db.commit()
    except UnsupportedDocument as exc:
        return _finish(
            db, version_id, VersionStatus.UNSUPPORTED.value, exc.reason_code
        )
    except SourceMissing as exc:
        # The file was there when it was scanned and has gone since. That is a
        # property of the folder, not of the document, and it is retryable, so
        # it is failed rather than unsupported.
        return _finish(
            db, version_id, VersionStatus.FAILED.value, exc.reason_code
        )
    except SourceChanged as exc:
        # The file was written while it was being read.
        return _finish(
            db, version_id, VersionStatus.FAILED.value, exc.reason_code
        )
    except Exception:
        # Everything from here on runs after the row was committed as
        # "extracting". If any step fails - the reader, the chunker or the
        # store - leaving the row mid-extraction makes it indistinguishable
        # from one that is still running, so the outcome is recorded before the
        # error goes up for the worker to decide whether to retry.
        db.rollback()
        _finish(db, version_id, VersionStatus.FAILED.value, REASON_PROCESSING_FAILED)
        raise

    return VersionStatus.BASIC_READY.value
