import { AdapterError } from "./errors.js";

const messages = {
  PATH_OUT_OF_SCOPE: "Choose a relative directory inside an approved read-only mount.",
  SOURCE_UNAVAILABLE: "Source unavailable. Re-check access to the authorized directory.",
  STALE_VERSION: "The source version changed. Reload the current file before viewing evidence.",
  ACTIVE_JOB_EXISTS: "A scan is already active. Open the existing job before submitting again.",
  AI_UNAVAILABLE: "Local AI is unavailable. Available keyword results remain usable.",
  version_superseded: "This passage belongs to an older file version. Refresh the current results.",
  no_current_version: "This file has no current indexed version.",
  file_missing: "The source file is no longer available in the authorized directory.",
  root_revoked: "This directory authorization is no longer active.",
  chunk_not_found: "The requested source passage is no longer available.",
  path_out_of_scope: "Choose a relative directory inside an approved read-only mount.",
  source_unavailable: "Source unavailable. Re-check access to the authorized directory.",
  active_job_exists: "A scan is already active. Open the existing job before submitting again.",
  unknown_mount: "This read-only mount is no longer configured.",
  review_conflict: "Another decision was saved. Reload the latest revision before reviewing again.",
  relationship_not_found: "This relation is no longer available. Reload the candidates.",
  corrected_entity_not_found: "The correction target does not exist. Check its entity ID.",
  correction_without_target: "Choose an existing entity ID for this correction.",
  invalid_decision: "Choose confirm, correct or reject.",
};
const contractError = () => new AdapterError("The service response does not match the D integration contract.", { status: 502, code: "CONTRACT_MISMATCH" });
const isId = (value) => typeof value === "string" && value.length > 0;
const isJobId = (value) => isId(value) || (Number.isSafeInteger(value) && value > 0);
const isRelativePath = (value) => isId(value) && !/^(?:[\\/]|[a-z]:)/i.test(value) && !value.split(/[\\/]/).includes("..");
const requireValue = (condition) => { if (!condition) throw contractError(); };
const jobStates = ["pending", "running", "retry_wait", "completed", "failed", "canceled"];
const searchModes = ["keyword", "semantic", "hybrid"];
const decisions = ["confirmed", "corrected", "rejected"];
const inScoreRange = (value) => Number.isFinite(value) && value >= 0 && value <= 1;
const safeErrorCode = (value) => value == null ? null : (
  [...Object.keys(messages), "encrypted", "corrupt", "no_text_layer", "unreadable", "unsupported_format", "source_changed", "processing_failed", "scan_failed", "job_failed", "SCAN_FAILED", "EMPTY_FILE", "CORRUPT_PDF", "TRUNCATED_PDF", "ENCRYPTED_PDF", "NO_TEXT_LAYER", "UNSUPPORTED_FORMAT", "JOB_FAILED"].includes(value) ? value : "JOB_FAILED"
);

export function createApiAdapter({ baseUrl = "/api", fetchImpl = globalThis.fetch, timeoutMs = 15000 } = {}) {
  async function request(path, { method = "GET", body, expectedStatus = 200 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(`${baseUrl.replace(/\/$/, "")}${path}`, {
        method, signal: controller.signal, credentials: "same-origin", cache: "no-store",
        headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const proposedCode = payload?.code || payload?.detail?.code;
        const code = Object.hasOwn(messages, proposedCode) ? proposedCode : `HTTP_${response.status}`;
        const message = messages[code] || (response.status === 404
          ? "The requested service resource is unavailable. Check that the file-management API is installed."
          : "The service could not complete this request. Check local service health and permissions.");
        // Do not render backend detail/stack traces or absolute host paths.
        throw new AdapterError(message, { status: response.status, code });
      }
      requireValue(response.status === expectedStatus && payload !== null);
      return payload;
    } catch (error) {
      if (error instanceof AdapterError) throw error;
      const timedOut = controller.signal.aborted;
      throw new AdapterError(timedOut
        ? "Request timed out. If this was an authorization request, verify acceptance before submitting again."
        : "Cannot reach the local API. Check the service and browser origin; no demo fallback was used.",
      { status: 0, code: timedOut ? "REQUEST_TIMEOUT" : "NETWORK_ERROR" });
    } finally { clearTimeout(timer); }
  }
  function array(payload, predicate) {
    requireValue(Array.isArray(payload) && payload.every(predicate));
    return payload;
  }
  return {
    mode: "api",
    async listMounts() {
      return array(await request("/mounts"), (item) => isId(item?.mount_id) && isId(item.label) && item.read_only === true);
    },
    async listDirectories(mountId) {
      return array(await request(`/mounts/${encodeURIComponent(mountId)}/directories`), (item) => isRelativePath(item?.relative_path) && isId(item.label));
    },
    async createRootScan(mountId, relativePath) {
      const payload = await request("/roots", { method: "POST", expectedStatus: 202, body: { mount_id: mountId, relative_path: relativePath } });
      requireValue(isId(payload.root_id) && isJobId(payload.job_id) && payload.status === "pending");
      return { ...payload, status_code: 202 };
    },
    async rescanRoot(rootId) {
      requireValue(isId(rootId));
      const payload = await request(`/roots/${encodeURIComponent(rootId)}/scans`, { method: "POST", expectedStatus: 202 });
      requireValue(payload.root_id === rootId && isJobId(payload.job_id) && payload.status === "pending");
      return { ...payload, status_code: 202 };
    },
    async retryJob(jobId, rootId) {
      requireValue(isJobId(jobId) && isId(rootId));
      const payload = await request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST", expectedStatus: 202 });
      requireValue(isJobId(payload.job_id) && String(payload.job_id) === String(jobId) &&
        payload.root_id === rootId && payload.status === "pending");
      return { ...payload, status_code: 202 };
    },
    async getJob(jobId) {
      const job = await request(`/jobs/${encodeURIComponent(jobId)}`);
      requireValue(isJobId(job.job_id) && String(job.job_id) === String(jobId) && isId(job.root_id) && jobStates.includes(job.status));
      return { ...job, error_code: safeErrorCode(job.error_code) };
    },
    async getRoot(rootId) {
      const root = await request(`/roots/${encodeURIComponent(rootId)}`);
      requireValue(root.root_id === rootId && isId(root.status));
      // Missing counters stay unknown; do not substitute scan-job counters or zeros.
      return root;
    },
    async listFiles(rootId) {
      const files = array(await request(`/files?root_id=${encodeURIComponent(rootId)}`), (item) =>
        isId(item?.file_id) && (item.version_id == null || isId(item.version_id)) && isId(item.display_name) &&
        isRelativePath(item.relative_path) && isId(item.status) && item.root_id === rootId);
      return files.map((file) => ({ ...file, error_code: safeErrorCode(file.error_code), expected_error_code: safeErrorCode(file.expected_error_code) }));
    },
    async search({ query, rootId = null, fileId = null, mode = "hybrid", topK = 10 }) {
      requireValue(typeof query === "string" && query.trim().length > 0 && query.trim().length <= 500);
      requireValue(searchModes.includes(mode) && Number.isInteger(topK) && topK >= 1 && topK <= 50);
      requireValue(rootId == null || isId(rootId));
      requireValue(fileId == null || isId(fileId));
      const payload = await request("/search", {
        method: "POST",
        body: { query: query.trim(), mode, top_k: topK, root_id: rootId, file_id: fileId },
      });
      const validResult = (item) =>
        isId(item?.root_id) && (rootId == null || item.root_id === rootId) &&
        isId(item.file_id) && (fileId == null || item.file_id === fileId) && isId(item.file_name) && isRelativePath(item.file_path) &&
        isId(item.version_id) && isId(item.chunk_id) && Number.isInteger(item.ordinal) && item.ordinal > 0 &&
        (item.page == null || (Number.isInteger(item.page) && item.page > 0)) &&
        typeof item.text === "string" && item.text.length <= 2000 && isId(item.reason) &&
        inScoreRange(item.score) && inScoreRange(item.keyword_score) && inScoreRange(item.semantic_score);
      requireValue(typeof payload.query === "string" && payload.query.length > 0 &&
        payload.mode === mode && searchModes.includes(payload.effective_mode) &&
        Number.isSafeInteger(payload.total) && payload.total >= 0 && Array.isArray(payload.results) &&
        payload.total >= payload.results.length && payload.results.length <= topK && payload.results.every(validResult) &&
        new Set(payload.results.map((item) => item.file_id)).size === payload.results.length &&
        typeof payload.degraded === "boolean" &&
        (payload.degraded ? /^[a-z][a-z0-9_]{1,63}$/.test(payload.degradation_reason || "") : payload.effective_mode === mode));
      return payload;
    },
    async getEvidenceByChunk(chunkId) {
      const evidence = await request(`/evidence/${encodeURIComponent(chunkId)}`);
      requireValue(isId(evidence.chunk_id) && evidence.chunk_id === chunkId &&
        isId(evidence.file_id) && isId(evidence.version_id) && isRelativePath(evidence.relative_path) &&
        (evidence.page_number == null || (Number.isInteger(evidence.page_number) && evidence.page_number > 0)) &&
        Number.isInteger(evidence.ordinal) && evidence.ordinal > 0 && typeof evidence.text === "string" &&
        /^[a-f0-9]{64}$/.test(evidence.content_sha256));
      return evidence;
    },
    async listRelations(versionId) {
      const relations = array(await request(`/versions/${encodeURIComponent(versionId)}/relations`), (item) =>
        isId(item?.relationship_id) && ["person", "project", "topic"].includes(item.entity_type) &&
        isId(item.label) && isId(item.relation_type) && typeof item.evidence_missing === "boolean" &&
        (item.page_number == null || (Number.isInteger(item.page_number) && item.page_number > 0)) &&
        typeof item.quote === "string" && (item.decision == null || decisions.includes(item.decision)) &&
        Number.isSafeInteger(item.decision_revision) && item.decision_revision >= 0 &&
        (item.corrected_entity_id == null || isId(item.corrected_entity_id)));
      requireValue(relations.length <= 20 && new Set(relations.map((item) => item.relationship_id)).size === relations.length);
      return relations;
    },
    async recordReview(relationshipId, { decision, expectedRevision, reason = "", actor, correctedEntityId = null }) {
      requireValue(decisions.includes(decision) && Number.isSafeInteger(expectedRevision) && expectedRevision >= 0 &&
        isId(actor?.trim()) && typeof reason === "string" &&
        (decision === "corrected" ? isId(correctedEntityId) : correctedEntityId == null));
      // No optimistic confirmation and no replay: only the server can advance the revision.
      const result = await request(`/relations/${encodeURIComponent(relationshipId)}/reviews`, {
        method: "POST", body: {
          decision, expected_revision: expectedRevision, reason: reason.trim(), actor: actor.trim(),
          ...(decision === "corrected" ? { corrected_entity_id: correctedEntityId } : {}),
        },
      });
      requireValue(Number.isSafeInteger(result.decision_revision) && result.decision_revision === expectedRevision + 1);
      return result;
    },
    async getEvidence(fileId, versionId) {
      return array(await request(`/files/${encodeURIComponent(fileId)}/evidence?version_id=${encodeURIComponent(versionId)}`), (item) =>
        item?.file_id === fileId && item.version_id === versionId && Number.isInteger(item.page) && item.page > 0 &&
        isRelativePath(item.source_path) && isId(item.excerpt));
    },
  };
}
