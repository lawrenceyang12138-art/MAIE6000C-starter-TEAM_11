"""Document parsing, chunking, evidence and relations.

This package is owned by the "read files" workstream. It turns a file on disk
into located pieces of text, and then into evidence-backed statements about
what that text mentions.

The pipeline, in the order the worker drives it:

    extract_document(path)          -> per-page text plus the file's identity
    chunk_document(document)        -> located, overlapping chunks
    persist_chunks(db, version, …)  -> store them against a file version
    candidate_relations(chunks)     -> entity candidates, each with its quote
    persist_relations(db, version, …) -> store entities, relations and evidence
    read_evidence(db, chunk_id)     -> serve a passage, or refuse if stale
    read_relationships(db, version) -> bounded relation list for display
    record_review(db, relation, …)  -> append a human decision with a revision;
                                       a correction also names the entity it
                                       points to instead
"""

from services.parsing.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    MIN_CHUNK_CHARS,
    Chunk,
    chunk_document,
    clean_page_text,
    strip_running_headers_footers,
)
from services.parsing.evidence import (
    REASON_CHUNK_NOT_FOUND,
    REASON_FILE_MISSING,
    REASON_NO_CURRENT_VERSION,
    REASON_ROOT_REVOKED,
    REASON_VERSION_SUPERSEDED,
    Evidence,
    SourceUnavailable,
    read_evidence,
)
from services.parsing.graph import (
    MAX_RELATIONSHIPS,
    REASON_CORRECTED_ENTITY_NOT_FOUND,
    REASON_CORRECTION_TARGET_NOT_ALLOWED,
    REASON_CORRECTION_WITHOUT_TARGET,
    REASON_INVALID_DECISION,
    REASON_RELATIONSHIP_NOT_FOUND,
    REASON_REVIEW_CONFLICT,
    RelationshipView,
    ReviewRefused,
    effective_decision,
    read_relationships,
    record_review,
)
from services.parsing.handler import (
    PARSER_REVISION,
    REASON_SOURCE_CHANGED,
    handle_extract_file,
)
from services.parsing.pdf import (
    REASON_UNSUPPORTED_FORMAT,
    ExtractedDocument,
    PageText,
    SourceChanged,
    SourceMissing,
    UnsupportedDocument,
    extract_document,
    file_identity,
)
from services.parsing.persist import (
    InvalidChunkSet,
    persist_chunks,
    persist_relations,
)
from services.parsing.relations import (
    ENTITY_PERSON,
    ENTITY_PROJECT,
    ENTITY_TOPIC,
    PRODUCER_REVISION,
    CandidateRelation,
    candidate_relations,
    find_mentions,
)

__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "CHUNK_SIZE_CHARS",
    "ENTITY_PERSON",
    "ENTITY_PROJECT",
    "ENTITY_TOPIC",
    "MAX_RELATIONSHIPS",
    "MIN_CHUNK_CHARS",
    "PARSER_REVISION",
    "PRODUCER_REVISION",
    "REASON_CHUNK_NOT_FOUND",
    "REASON_CORRECTED_ENTITY_NOT_FOUND",
    "REASON_CORRECTION_TARGET_NOT_ALLOWED",
    "REASON_CORRECTION_WITHOUT_TARGET",
    "REASON_FILE_MISSING",
    "REASON_INVALID_DECISION",
    "REASON_NO_CURRENT_VERSION",
    "REASON_RELATIONSHIP_NOT_FOUND",
    "REASON_REVIEW_CONFLICT",
    "REASON_ROOT_REVOKED",
    "REASON_SOURCE_CHANGED",
    "REASON_UNSUPPORTED_FORMAT",
    "REASON_VERSION_SUPERSEDED",
    "CandidateRelation",
    "Chunk",
    "Evidence",
    "ExtractedDocument",
    "InvalidChunkSet",
    "PageText",
    "RelationshipView",
    "ReviewRefused",
    "SourceUnavailable",
    "SourceMissing",
    "SourceChanged",
    "UnsupportedDocument",
    "candidate_relations",
    "chunk_document",
    "clean_page_text",
    "effective_decision",
    "extract_document",
    "file_identity",
    "find_mentions",
    "handle_extract_file",
    "persist_chunks",
    "persist_relations",
    "read_evidence",
    "read_relationships",
    "record_review",
    "strip_running_headers_footers",
]
