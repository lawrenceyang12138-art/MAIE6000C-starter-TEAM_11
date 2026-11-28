import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./app.jsx";

const fetchImpl = vi.hoisted(() => vi.fn());
vi.mock("./api/adapter.js", async (importOriginal) => {
  const adapters = await importOriginal();
  return { ...adapters, createAdapter: () => adapters.createApiAdapter({ fetchImpl }) };
});

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const response = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });
const setup = {
  state: "disabled", ready: false, progress: null, stage_progress: null,
  downloaded_bytes: 0, total_bytes: null, completed_files: 0, total_files: 0,
  model: "disabled-test-model", message: "Disabled", retryable: false,
  error_code: null, updated_at: "2026-11-27T00:00:00Z",
};

function stubApi(name, page, ordinal) {
  const file = {
    root_id: "root", file_id: "file", version_id: "version", relative_path: `notes/${name}`,
    display_name: name, presence_status: "present", status: "basic_ready", page_count: page ?? 0,
  };
  const hit = {
    root_id: file.root_id, file_id: file.file_id, version_id: file.version_id,
    file_name: name, file_path: file.relative_path, chunk_id: "matching-chunk", page, ordinal,
    text: "Beacon search excerpt", reason: "keyword: beacon", score: 1, keyword_score: 1, semantic_score: 0,
  };
  const source = {
    chunk_id: hit.chunk_id, file_id: file.file_id, version_id: file.version_id,
    relative_path: file.relative_path, page_number: page, ordinal,
    text: "Beacon search excerpt\nSecond line of the original passage.", content_sha256: "b".repeat(64),
  };
  const readSource = vi.fn().mockResolvedValue(response(source));
  fetchImpl.mockImplementation(async (path, options) => {
    if (path === "/api/setup") return response(setup);
    if (path === "/api/files?root_id=root") return response([file]);
    if (path === "/api/search" && options.method === "POST") {
      return response({ query: "beacon", mode: "keyword", effective_mode: "keyword", total: 1, degraded: false, results: [hit] });
    }
    if (path === "/api/evidence/matching-chunk" && options.method === "GET") return readSource();
    throw new Error(`Unexpected test API route: ${path}`);
  });
  return { file, source, readSource };
}

let container, root;
beforeEach(() => {
  fetchImpl.mockReset();
  window.history.replaceState({}, "", "/results/root");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.sessionStorage.clear();
});

async function search() {
  await act(async () => root.render(<App />));
  const input = container.querySelector('input[aria-label="Search query"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "beacon");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => input.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
}

const inspect = () => act(async () => container.querySelector(".file-row-main").click());

describe("version-bound search evidence (HTTP fixtures)", () => {
  it.each([
    ["minutes.pdf", 7, 12, "Page 7"],
    ["notes.txt", null, 5, "原文片段 #5"],
    ["notes.md", null, 8, "原文片段 #8"],
    ["notes.docx", null, 11, "原文片段 #11"],
  ])("opens the matched chunk for %s with its actual locator", async (name, page, ordinal, locator) => {
    const { source, readSource } = stubApi(name, page, ordinal);
    await search();
    expect(container.querySelector(".passage-locator").textContent).toBe(locator);
    await inspect();
    expect(readSource).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".evidence-record .page-index").textContent).toBe(locator);
    expect(container.querySelector(".evidence-record strong").textContent).toBe(source.relative_path);
    expect(container.querySelector(".evidence-record p").textContent).toBe(source.text);
    expect(container.querySelector(".evidence-detail-heading code").textContent).toBe(source.version_id);
    expect(container.querySelector(".evidence-hash").textContent).toContain(source.content_sha256);
    expect(fetchImpl.mock.calls.some(([path]) => /^\/api\/files\//.test(path))).toBe(false);
    expect(container.querySelector(".inspector-pane").textContent).not.toContain("Page unknown");
  });

  it.each([{ version_id: "older-version" }, { ordinal: 1 }, { page_number: 1 }])(
    "refuses the matched chunk if evidence locators no longer match: %j", async (change) => {
      const { source, readSource } = stubApi("notes.txt", null, 5);
      readSource.mockResolvedValue(response({ ...source, ...change }));
      await search();
      await inspect();
      expect(container.querySelector(".evidence-record")).toBeNull();
      expect(container.querySelector(".inspector-pane [role=alert]").textContent).toContain("version_superseded");
      expect(container.textContent).not.toContain(source.text);
    });

  it.each(["source_changed", "path_out_of_scope"])("does not reuse an opened passage after %s", async (code) => {
    const { source, readSource } = stubApi("notes.txt", null, 5);
    await search();
    await inspect();
    expect(container.querySelector(".evidence-record p").textContent).toBe(source.text);
    await act(async () => container.querySelector('button[aria-label="Close inspector"]').click());
    readSource.mockResolvedValue(response({ detail: { code } }, code === "source_changed" ? 409 : 403));
    await inspect();
    expect(readSource).toHaveBeenCalledTimes(2);
    expect(container.querySelector(".evidence-record")).toBeNull();
    expect(container.querySelector(".inspector-pane [role=alert]").textContent).toContain(code);
    expect(container.textContent).not.toContain("Beacon search excerpt");
  });
});
