export function normalizeQuery(value) {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ");
}

export function searchHitFile(hit, catalog = []) {
  const current = catalog.find((file) => file.file_id === hit.file_id && file.version_id === hit.version_id);
  return {
    ...current,
    root_id: hit.root_id,
    file_id: hit.file_id,
    version_id: hit.version_id,
    display_name: hit.file_name,
    relative_path: hit.file_path,
    status: current?.status || "basic_ready",
    snippet: hit.text,
    search_hit: hit,
  };
}

export function evidenceMatchesHit(evidence, hit) {
  return evidence?.chunk_id === hit.chunk_id && evidence.file_id === hit.file_id &&
    evidence.version_id === hit.version_id && evidence.ordinal === hit.ordinal &&
    evidence.page_number === hit.page &&
    evidence.relative_path.replaceAll("\\", "/") === hit.file_path.replaceAll("\\", "/");
}

export function evidenceRecord(evidence) {
  return { ...evidence, evidence_id: evidence.chunk_id, page: evidence.page_number,
    source_path: evidence.relative_path, excerpt: evidence.text };
}

export function degradationMessage(reason) {
  const messages = {
    ai_disabled: "Local AI is disabled. Keyword search remains available.",
    ai_timeout: "Local AI timed out. Keyword search was used.",
    ai_unavailable: "Local AI is unavailable. Keyword search remains available.",
    embeddings_not_ready: "Document vectors are not ready. Keyword search was used.",
    partial_embeddings: "Only some documents have compatible vectors. Results may be incomplete.",
    mock_keyword_only: "Synthetic keyword simulation. No semantic model was run.",
  };
  return messages[reason] || "Search ran with reduced capabilities. Check the effective mode below.";
}
