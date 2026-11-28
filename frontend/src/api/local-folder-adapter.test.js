import { describe, expect, it, vi } from "vitest";
import { createLocalFolderAdapter } from "./local-folder-adapter.js";

const id = "1a0b6735-3aa7-4e0e-879c-d2af842bcc79";
const status = { available: true, protocol: 1, project_id: "test-project", session_token: "private-session" };
const selection = { operation_id: id, state: "selected", folder_name: "我的资料", display_path: "D:\\我的资料" };
const response = (payload, code = 200) => ({ ok: code < 400, status: code, json: async () => payload });

describe("local folder bridge adapter", () => {
  it("keeps the session in headers and sends only an operation ID when choosing", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(selection, 202));
    const adapter = createLocalFolderAdapter({ fetchImpl });
    expect(await adapter.startSelection(id)).toEqual(selection);
    expect(fetchImpl.mock.calls[0][0]).toBe("http://127.0.0.1:8765/status");
    const [url, request] = fetchImpl.mock.calls[1];
    expect(url).toBe("http://127.0.0.1:8765/folder-selections");
    expect(request.headers["X-FileTrace-Session"]).toBe("private-session");
    expect(JSON.parse(request.body)).toEqual({ operation_id: id });
    expect(request.credentials).toBe("omit");
  });

  it("prepares the saved selection without accepting a host path from the caller", async () => {
    const ready = { ...selection, state: "ready", mount_id: "local-test" };
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response(ready, 202)).mockResolvedValueOnce(response(ready));
    const adapter = createLocalFolderAdapter({ fetchImpl });
    await adapter.prepare(id);
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body)).toEqual({});
    expect(fetchImpl.mock.calls[1][0]).toBe(`http://127.0.0.1:8765/folder-selections/${id}/prepare`);
    expect(await adapter.getOperation(id)).toEqual(ready);
    expect(fetchImpl.mock.calls.filter(([url]) => url.endsWith("/status"))).toHaveLength(1);
  });

  it.each([
    { operation_id: "other" }, { state: "unknown" }, { state: "ready", mount_id: null }, { display_path: null }, { error_code: "C:\\private" },
  ])("rejects a mismatched operation or unsafe contract %j", async (changes) => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response({ ...selection, ...changes }));
    await expect(createLocalFolderAdapter({ fetchImpl }).getOperation(id)).rejects.toMatchObject({ code: "LOCAL_FOLDER_CONTRACT_MISMATCH" });
  });

  it("does not expose the token returned by discovery to components", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(status));
    const result = await createLocalFolderAdapter({ fetchImpl }).getStatus();
    expect(result).toEqual({ available: true, protocol: 1, project_id: "test-project" });
  });

  it("reports a lost selection POST without replaying it or using API mock data", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(status)).mockRejectedValueOnce(new TypeError("lost response"));
    await expect(createLocalFolderAdapter({ fetchImpl }).startSelection(id)).rejects.toMatchObject({ code: "LOCAL_FOLDER_UNAVAILABLE" });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("allows only loopback service addresses", () => {
    for (const baseUrl of ["https://example.com", "http://192.168.0.1:8765", "http://user:pass@localhost:8765", "http://localhost:8765/path"]) {
      expect(() => createLocalFolderAdapter({ baseUrl })).toThrow("loopback");
    }
  });

  it("re-discovers a restarted helper session on the next read", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(status)).mockResolvedValueOnce(response({}, 403))
      .mockResolvedValueOnce(response({ ...status, session_token: "new-session" })).mockResolvedValueOnce(response(selection));
    const adapter = createLocalFolderAdapter({ fetchImpl });
    await expect(adapter.getOperation(id)).rejects.toMatchObject({ status: 403 });
    await adapter.getOperation(id);
    expect(fetchImpl.mock.calls[3][1].headers["X-FileTrace-Session"]).toBe("new-session");
  });
});
