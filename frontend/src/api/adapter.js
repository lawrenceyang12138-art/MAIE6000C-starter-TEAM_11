import mockData from "../mock/data.json" with { type: "json" };
import { AdapterError } from "./errors.js";
import { createMockAdapter } from "./mock-adapter.js";

export { AdapterError, createMockAdapter };

async function requestJson(baseUrl, path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new AdapterError(payload.detail || "Request failed.", {
      status: response.status,
      code: payload.code || "HTTP_ERROR",
    });
  }
  return payload;
}

export function createApiAdapter({ baseUrl = "http://localhost:8000" } = {}) {
  return {
    mode: "api",
    listMounts: () => requestJson(baseUrl, "/mounts"),
    listDirectories: (mountId) => requestJson(baseUrl, `/mounts/${encodeURIComponent(mountId)}/directories`),
    createRootScan: (mountId, relativePath) =>
      requestJson(baseUrl, "/roots", { method: "POST", body: JSON.stringify({ mount_id: mountId, relative_path: relativePath }) }),
    getJob: (jobId) => requestJson(baseUrl, `/jobs/${encodeURIComponent(jobId)}`),
    listFiles: (rootId) => requestJson(baseUrl, `/files?root_id=${encodeURIComponent(rootId)}`),
    getEvidence: (fileId, versionId) =>
      requestJson(baseUrl, `/files/${encodeURIComponent(fileId)}/evidence?version_id=${encodeURIComponent(versionId)}`),
  };
}

export function createAdapter() {
  const mode = import.meta.env.VITE_DATA_MODE || "mock";
  return mode === "api"
    ? createApiAdapter({ baseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000" })
    : createMockAdapter();
}
