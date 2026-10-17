import { AdapterError } from "./errors.js";

const messages = {
  PATH_OUT_OF_SCOPE: "Choose a relative directory inside an approved read-only mount.",
  SOURCE_UNAVAILABLE: "Source unavailable. Re-check access to the authorized directory.",
  STALE_VERSION: "The source version changed. Reload the current file before viewing evidence.",
  ACTIVE_JOB_EXISTS: "A scan is already active. Open the existing job before submitting again.",
  AI_UNAVAILABLE: "Local AI is unavailable. Available keyword results remain usable.",
  path_out_of_scope: "Choose a relative directory inside an approved read-only mount.",
  active_job_exists: "A scan is already active for this directory.",
  unknown_mount: "The configured mount is not available.",
  mount_unavailable: "The configured source folder is unavailable.",
  version_superseded: "The source version changed. Reload the current file before viewing evidence.",
  chunk_not_found: "The requested passage is no longer available.",
  file_missing: "The source file is no longer available.",
  root_revoked: "Access to this directory has been revoked.",
  no_current_version: "The current version is not ready yet.",
  review_conflict: "Someone else reviewed this item first. Reload and try again.",
  invalid_decision: "The selected review decision is invalid.",
  correction_without_target: "A correction must name the replacement entity.",
  correction_target_not_allowed: "Only a correction may name a replacement entity.",
  corrected_entity_not_found: "The replacement entity no longer exists.",
};
const contractError = () => new AdapterError("The service response does not match the D integration contract.", { status: 502, code: "CONTRACT_MISMATCH" });
const isId = (value) => typeof value === "string" && value.length > 0;
const isRelativePath = (value) => isId(value) && !/^(?:[\\/]|[a-z]:)/i.test(value) && !value.split(/[\\/]/).includes("..");
const requireValue = (condition) => { if (!condition) throw contractError(); };
const jobStates = ["pending", "running", "retry_wait", "completed", "failed", "canceled"];
const safeErrorCode = (value) => value == null ? null : (
  [...Object.keys(messages), "SCAN_FAILED", "EMPTY_FILE", "CORRUPT_PDF", "TRUNCATED_PDF", "ENCRYPTED_PDF", "NO_TEXT_LAYER", "UNSUPPORTED_FORMAT", "JOB_FAILED", "encrypted", "corrupt", "no_text_layer", "unsupported_format", "source_changed", "file_missing", "processing_failed"].includes(value) ? value : "JOB_FAILED"
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
      requireValue(isId(payload.root_id) && Number.isInteger(payload.job_id) && payload.status === "pending");
      return { ...payload, status_code: 202 };
    },
    async getJob(jobId) {
      const job = await request(`/jobs/${encodeURIComponent(jobId)}`);
      requireValue(String(job.job_id) === String(jobId) && isId(job.root_id) && jobStates.includes(job.status));
      return { ...job, error_code: safeErrorCode(job.error_code) };
    },
    async retryJob(jobId) {
      const job = await request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
      requireValue(String(job.job_id) === String(jobId) && isId(job.root_id) && jobStates.includes(job.status));
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
        isId(item?.file_id) && isId(item.version_id) && isId(item.display_name) &&
        isRelativePath(item.relative_path) && isId(item.status) && item.root_id === rootId);
      return files.map((file) => ({ ...file, error_code: safeErrorCode(file.error_code), expected_error_code: safeErrorCode(file.expected_error_code) }));
    },
    async getEvidence(fileId, versionId) {
      return array(await request(`/files/${encodeURIComponent(fileId)}/evidence?version_id=${encodeURIComponent(versionId)}`), (item) =>
        item?.file_id === fileId && item.version_id === versionId && Number.isInteger(item.page) && item.page > 0 &&
        isRelativePath(item.source_path) && isId(item.excerpt));
    },
    async search(query, rootId, { mode = "keyword", topK = 10 } = {}) {
      const payload = await request("/search", {
        method: "POST",
        body: { query, mode, top_k: topK, root_id: rootId },
      });
      requireValue(
        payload &&
        isId(payload.query) &&
        isId(payload.effective_mode) &&
        Array.isArray(payload.results) &&
        payload.results.every((item) =>
          isId(item.file_id) &&
          isId(item.version_id) &&
          isId(item.chunk_id) &&
          isId(item.file_name) &&
          isRelativePath(item.file_path) &&
          isId(item.text)),
      );
      return payload;
    },
    async getEvidenceByChunk(chunkId) {
      const item = await request(`/evidence/${encodeURIComponent(chunkId)}`);
      requireValue(
        item?.chunk_id === chunkId &&
        isId(item.file_id) &&
        isId(item.version_id) &&
        isId(item.relative_path) &&
        isId(item.text),
      );
      return [{
        evidence_id: item.chunk_id,
        file_id: item.file_id,
        version_id: item.version_id,
        page: item.page_number,
        source_path: item.relative_path,
        excerpt: item.text,
      }];
    },
  };
}
