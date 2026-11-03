import { AdapterError } from "./errors.js";

const states = new Set(["selecting", "selected", "waiting", "preparing", "reconnecting", "ready", "cancelled", "failed"]);
const idPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const validString = (value) => typeof value === "string" && value.length > 0;
const mismatch = () => new AdapterError("The local folder service returned an invalid response.", { status: 502, code: "LOCAL_FOLDER_CONTRACT_MISMATCH" });

export function createLocalFolderAdapter({
  baseUrl = import.meta.env?.VITE_LOCAL_FOLDER_BRIDGE_URL || "http://127.0.0.1:8765",
  fetchImpl = globalThis.fetch,
  timeoutMs = 5000,
} = {}) {
  const url = new URL(baseUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname)) {
    throw new Error("The local folder service must use a loopback HTTP origin.");
  }
  let sessionToken = null;

  async function request(path, { method = "GET", body, signal, expectedStatus = 200, authenticate = true } = {}) {
    if (authenticate && !sessionToken) await getStatus({ signal });
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (signal?.aborted) cancel();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(cancel, timeoutMs);
    try {
      const response = await fetchImpl(url.origin + path, {
        method, signal: controller.signal, credentials: "omit", cache: "no-store",
        headers: { Accept: "application/json", ...(authenticate ? { "X-FileTrace-Session": sessionToken } : {}), ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        if ([401, 403].includes(response.status)) sessionToken = null;
        throw new AdapterError(response.status === 404
          ? "The saved folder selection was not found by the local service. Resume it to reopen the folder picker."
          : "The local folder service could not complete this request. Check the launcher and local access permission.",
        { status: response.status, code: response.status === 404 ? "LOCAL_FOLDER_NOT_FOUND" : "LOCAL_FOLDER_REQUEST_FAILED" });
      }
      if (response.status !== expectedStatus || !payload) throw mismatch();
      return payload;
    } catch (error) {
      if (error instanceof AdapterError) throw error;
      throw new AdapterError("Cannot reach the local folder service. Start it with python scripts/start.py, then check the connection.", { status: 0, code: "LOCAL_FOLDER_UNAVAILABLE" });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
  }

  async function getStatus({ signal } = {}) {
    const status = await request("/status", { signal, authenticate: false });
    if (status.available !== true || status.protocol !== 1 || !validString(status.project_id) || !validString(status.session_token)) throw mismatch();
    sessionToken = status.session_token;
    return { available: true, protocol: 1, project_id: status.project_id };
  }

  function operation(payload, operationId) {
    if (payload.operation_id !== operationId || !states.has(payload.state) ||
      (["selected", "waiting", "preparing", "reconnecting", "ready"].includes(payload.state) && (!validString(payload.folder_name) || !validString(payload.display_path))) ||
      (payload.state === "ready" && !validString(payload.mount_id)) ||
      (payload.error_code != null && !/^[a-z][a-z0-9_]{1,63}$/.test(payload.error_code))) throw mismatch();
    return payload;
  }

  function requireId(operationId) {
    if (!idPattern.test(operationId)) throw mismatch();
  }

  return {
    getStatus,
    async startSelection(operationId, { signal } = {}) {
      requireId(operationId);
      return operation(await request("/folder-selections", { method: "POST", body: { operation_id: operationId }, signal, expectedStatus: 202 }), operationId);
    },
    async getOperation(operationId, { signal } = {}) {
      requireId(operationId);
      return operation(await request(`/folder-selections/${encodeURIComponent(operationId)}`, { signal }), operationId);
    },
    async prepare(operationId, { signal } = {}) {
      requireId(operationId);
      return operation(await request(`/folder-selections/${encodeURIComponent(operationId)}/prepare`, { method: "POST", body: {}, signal, expectedStatus: 202 }), operationId);
    },
  };
}
