import assert from "node:assert/strict";
import { test } from "node:test";
import { createApiAdapter } from "../frontend/src/api/http-adapter.js";
import { createAdapter } from "../frontend/src/api/adapter.js";
import { createMockAdapter } from "../frontend/src/api/mock-adapter.js";
import data from "../frontend/src/mock/data.json" with { type: "json" };
import { dedupeFiles, isEvidenceForVersion, isSourceUnavailable, shouldPoll, summarizeProgress } from "../frontend/src/lib/scan.js";

const response = (body, status = 200) => new Response(JSON.stringify(body), { status });
const counts = { total: 16, basic_ready: 12, enriched: 0, failed: 3, unsupported: 1 };
const root = { root_id: "root-real", status: "active", availability: "available", file_counts: counts };
const mockApi = (body, status = 200) => createApiAdapter({ fetchImpl: async () => response(body, status) });

test("API is the default; explicit mock construction works and invalid mode fails", async () => {
  assert.equal(createAdapter().mode, "api");
  assert.equal((await createAdapter({ mode: "mock" }).listMounts())[0].read_only, true);
  assert.throws(() => createAdapter({ mode: "typo" }));
});

test("authorization sends only mount/path, checks actual HTTP 202 and preserves service IDs", async () => {
  let call;
  const api = createApiAdapter({ baseUrl: "/api/", fetchImpl: async (url, options) => {
    call = { url, options };
    return response({ root_id: "root-real", job_id: 42, status: "pending" }, 202);
  } });
  const accepted = await api.createRootScan("mount-real", "two/subfolders");
  assert.equal(call.url, "/api/roots");
  assert.equal(call.options.method, "POST");
  assert.deepEqual(JSON.parse(call.options.body), { mount_id: "mount-real", relative_path: "two/subfolders" });
  assert.equal(accepted.job_id, 42);
  assert.equal(accepted.status_code, 202);
});

for (const [label, payload, status] of [
  ["HTTP 200 masquerading as 202", { root_id: "r", job_id: 42, status: "pending", status_code: 202 }, 200],
  ["missing identifiers", { status: "pending" }, 202],
  ["premature completion", { root_id: "r", job_id: 42, status: "completed" }, 202],
]) test(`rejects ${label}`, async () => {
  await assert.rejects(mockApi(payload, status).createRootScan("m", "."), { code: "CONTRACT_MISMATCH" });
});

for (const status of [403, 404, 409, 422, 500, 503]) test(`HTTP ${status} is not converted to mock or empty success`, async () => {
  await assert.rejects(mockApi({ detail: "C:\\private\\sensitive.txt traceback" }, status).listMounts(), (error) =>
    error.status === status && error.code === `HTTP_${status}` && !error.message.includes("private"));
});

test("structured FastAPI errors are mapped to safe, actionable messages", async () => {
  await assert.rejects(mockApi({ detail: { code: "STALE_VERSION", message: "secret" } }, 409).getEvidence("f", "v"),
    (error) => error.code === "STALE_VERSION" && !error.message.includes("secret"));
});

test("network failure is explicit and authorization is never replayed", async () => {
  let calls = 0;
  const api = createApiAdapter({ fetchImpl: async () => { calls += 1; throw new TypeError("private network details"); } });
  await assert.rejects(api.createRootScan("m", "."), { status: 0, code: "NETWORK_ERROR" });
  assert.equal(calls, 1);
});

test("timeout aborts a request and explains acceptance uncertainty", async () => {
  const api = createApiAdapter({ timeoutMs: 2, fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }) });
  await assert.rejects(api.createRootScan("m", "."), (error) => error.code === "REQUEST_TIMEOUT" && error.message.includes("verify acceptance"));
});

test("successful HTML or invalid JSON is a contract failure, not zero mounts", async () => {
  const api = createApiAdapter({ fetchImpl: async () => new Response("<html>SPA fallback</html>", { status: 200 }) });
  await assert.rejects(api.listMounts(), { code: "CONTRACT_MISMATCH" });
});

test("mount and directory reads validate contract and URL-encode identifiers", async () => {
  const urls = [];
  const api = createApiAdapter({ fetchImpl: async (url) => {
    urls.push(url);
    return response(url.endsWith("/mounts") ? [{ mount_id: "m", label: "Read only", read_only: true }] : [{ relative_path: ".", label: "All fixtures" }]);
  } });
  assert.equal((await api.listMounts()).length, 1);
  assert.equal((await api.listDirectories("a/b")).length, 1);
  assert.equal(urls[1], "/api/mounts/a%2Fb/directories");
  await assert.rejects(mockApi([{ mount_id: "m", label: "Writable", read_only: false }]).listMounts());
  await assert.rejects(mockApi([{ relative_path: "C:\\private", label: "Host path" }]).listDirectories("m"));
});

test("job and root reads reject wrong-scope IDs and starter integer-job schema", async () => {
  await assert.rejects(mockApi({ id: 1, status: "claimed" }).getJob("1"), { code: "CONTRACT_MISMATCH" });
  await assert.rejects(mockApi({ job_id: "other", root_id: "r", status: "completed" }).getJob("j"));
  await assert.rejects(mockApi(root).getRoot("wrong"));
  assert.deepEqual(await mockApi(root).getRoot("root-real"), root);
  const unsafeJob = { job_id: "j", root_id: "r", status: "failed", error_code: "C:\\private\\error.log" };
  assert.equal((await mockApi(unsafeJob).getJob("j")).error_code, "JOB_FAILED");
});

test("file reads validate scope; evidence is file/version/page-bound", async () => {
  const file = { file_id: "f", version_id: "v", root_id: "r", display_name: "f.pdf", relative_path: "sub/f.pdf", status: "basic_ready" };
  assert.equal((await mockApi([file]).listFiles("r")).length, 1);
  await assert.rejects(mockApi([file]).listFiles("wrong"));
  await assert.rejects(mockApi([{ ...file, relative_path: "../private.pdf" }]).listFiles("r"));
  const evidence = { file_id: "f", version_id: "v", page: 2, source_path: "sub/f.pdf", excerpt: "source passage" };
  assert.equal((await mockApi([evidence]).getEvidence("f", "v"))[0].page, 2);
  for (const changed of [{ version_id: "old" }, { file_id: "other" }, { page: 1.5 }, { page: 0 }]) {
    await assert.rejects(mockApi([{ ...evidence, ...changed }]).getEvidence("f", "v"));
  }
});

test("12/3/1 counters derive from root file stages, never the scan-job percent", () => {
  assert.deepEqual(summarizeProgress(root), { known: true, total: 16, processed: 16, normal: 12, abnormal: 3, unsupported: 1, pending: 0, percent: 100 });
  assert.equal(summarizeProgress({ status: "completed", total: 16, normal: 12, percent: 100 }).known, false);
});

test("discovery completion continues polling while files are pending", () => {
  const pending = { file_counts: { ...counts, basic_ready: 2, failed: 0, unsupported: 0 } };
  assert.equal(summarizeProgress(pending).pending, 14);
  assert.equal(shouldPoll({ status: "completed" }, pending), true);
  assert.equal(shouldPoll({ status: "completed" }, root), false);
  assert.equal(shouldPoll({ status: "failed" }, pending), false);
  assert.equal(shouldPoll({ status: "canceled" }, pending), false);
  assert.equal(shouldPoll({ status: "retry_wait" }, root), true);
});

for (const invalid of [undefined, {}, { ...counts, total: -1 }, { ...counts, failed: 2.5 }, { ...counts, total: 10 }, { ...counts, total: "16" }]) {
  test(`missing/invalid counters stay unknown (${JSON.stringify(invalid)})`, () => {
    const progress = summarizeProgress({ file_counts: invalid });
    assert.equal(progress.known, false);
    assert.equal(progress.percent, null);
    assert.equal(progress.normal, null);
  });
}

test("empty is distinct from failed read and unknown counters", () => {
  const empty = { file_counts: { total: 0, basic_ready: 0, enriched: 0, failed: 0, unsupported: 0 } };
  assert.equal(summarizeProgress(empty).percent, 100);
  assert.equal(shouldPoll({ status: "completed" }, empty), false);
});

test("duplicate file/version rows collapse; a new version is not confused with the old", () => {
  const files = [{ file_id: "f", version_id: "v1" }, { file_id: "f", version_id: "v1" }, { file_id: "f", version_id: "v2" }];
  assert.equal(dedupeFiles(files).length, 2);
  assert.equal(isEvidenceForVersion(null, "f", "v"), false);
  assert.equal(isEvidenceForVersion([{ file_id: "f", version_id: "v", page: 0.5 }], "f", "v"), false);
});

test("mock root counters, missing source and keyword-only states remain explicitly synthetic", async () => {
  const mock = createMockAdapter(data, { latency: 0 });
  const accepted = await mock.createRootScan("mount-team11-demo", "normal");
  for (let index = 0; index < 4; index += 1) await mock.getJob(accepted.job_id);
  assert.equal(summarizeProgress(await mock.getRoot(accepted.root_id)).normal, 12);
  await assert.rejects(mock.getEvidence("file-004", "version-004-v1"), { code: "SOURCE_UNAVAILABLE" });
  assert.equal((await mock.listFiles(accepted.root_id)).find((item) => item.file_id === "file-005").capability_status, "keyword_only");
});

test("mock rejects cached evidence from historical versions", async () => {
  const changed = structuredClone(data);
  changed.files[0].version_id = "version-new";
  await assert.rejects(createMockAdapter(changed, { latency: 0 }).getEvidence("file-001", "version-001-v1"), { code: "STALE_VERSION" });
});

test("explicit missing-source flag is classified as unsafe for current evidence", () => {
  assert.equal(isSourceUnavailable({ status: "basic_ready", source_available: false }), true);
  assert.equal(isSourceUnavailable({ status: "basic_ready", source_available: true }), false);
});

test("stale, missing and unreadable file states override an outdated available flag", () => {
  for (const status of ["stale", "missing", "unreadable"]) {
    assert.equal(isSourceUnavailable({ status, source_available: true }), true);
  }
  assert.equal(isSourceUnavailable({ status: "basic_ready", capability_status: "keyword_only" }), false);
});

test("source-unavailable and stale-version evidence errors invalidate previously cached passages", () => {
  for (const code of ["SOURCE_UNAVAILABLE", "STALE_VERSION"]) {
    assert.equal(isSourceUnavailable({ status: "basic_ready" }, { code }), true);
  }
  assert.equal(isSourceUnavailable({ status: "basic_ready" }, { code: "NETWORK_ERROR" }), false);
});

test("evidence must match the selected source path and its real page bound", () => {
  const item = { file_id: "f", version_id: "v", page: 2, source_path: "sub/file.pdf" };
  const scope = { sourcePath: "sub/file.pdf", pageCount: 3 };
  assert.equal(isEvidenceForVersion([item], "f", "v", scope), true);
  assert.equal(isEvidenceForVersion([{ ...item, source_path: "sub\\file.pdf" }], "f", "v", scope), true);
  assert.equal(isEvidenceForVersion([{ ...item, source_path: "other/file.pdf" }], "f", "v", scope), false);
  assert.equal(isEvidenceForVersion([{ ...item, page: 4 }], "f", "v", scope), false);
});

test("malformed evidence entries and invalid page-count metadata fail closed", () => {
  assert.equal(isEvidenceForVersion([null], "f", "v"), false);
  const item = { file_id: "f", version_id: "v", page: 1, source_path: "f.pdf" };
  for (const pageCount of [-1, 1.5, "3", null]) {
    assert.equal(isEvidenceForVersion([item], "f", "v", { pageCount }), false);
  }
  assert.equal(isEvidenceForVersion([item], "f", "v", { sourcePath: "f.pdf" }), true);
  assert.equal(isEvidenceForVersion([{ ...item, source_path: 7 }], "f", "v", { sourcePath: "f.pdf" }), false);
  assert.equal(isEvidenceForVersion([item], "f", "v", { sourcePath: null }), false);
});
