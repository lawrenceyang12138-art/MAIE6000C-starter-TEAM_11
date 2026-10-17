import { createMockAdapter } from "./mock-adapter.js";
import { AdapterError } from "./errors.js";
import mockData from "../mock/data.json" with { type: "json" };

describe("mock file-management adapter", () => {
  it("returns the 202 root/job contract and advances progress", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    const accepted = await adapter.createRootScan("mount-team11-demo", "normal");
    expect(accepted).toMatchObject({ status_code: 202, root_id: "root-demo-01", status: "pending" });
    expect(accepted.job_id).toBe("job-scan-demo-01");

    const first = await adapter.getJob(accepted.job_id);
    const second = await adapter.getJob(accepted.job_id);
    const final = await adapter.getJob(accepted.job_id);
    expect(first.status).toBe("pending");
    expect(second.status).toBe("running");
    expect(final.processed).toBeGreaterThan(second.processed);
  });

  it("shows an empty directory as a successful zero-file scan", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    const accepted = await adapter.createRootScan("mount-team11-demo", "empty");
    expect(accepted.root_id).toBe("root-empty-01");
    expect(await adapter.listFiles(accepted.root_id)).toEqual([]);
    await adapter.getJob(accepted.job_id);
    expect((await adapter.getJob(accepted.job_id)).status).toBe("completed");
  });

  it("rejects unknown mounts, unsafe paths, and an active duplicate scan", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    await expect(adapter.createRootScan("missing", "normal")).rejects.toMatchObject({ status: 404, code: "UNKNOWN_MOUNT" });
    await expect(adapter.createRootScan("mount-team11-demo", "../outside")).rejects.toMatchObject({ status: 403, code: "PATH_OUT_OF_SCOPE" });
    await adapter.createRootScan("mount-team11-demo", "normal");
    await expect(adapter.createRootScan("mount-team11-demo", "normal")).rejects.toMatchObject({ status: 409, code: "ACTIVE_JOB_EXISTS" });
  });

  it("returns page evidence and rejects stale versions", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    const evidence = await adapter.getEvidence("file-009", "version-009-v1");
    expect(evidence).toHaveLength(3);
    expect(evidence[0]).toMatchObject({ file_id: "file-009", version_id: "version-009-v1", page: 1 });
    await expect(adapter.getEvidence("file-009", "version-009-v2")).rejects.toBeInstanceOf(AdapterError);
  });

  it("surfaces a missing source and a search capability downgrade", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    const files = await adapter.listFiles("root-demo-01");
    expect(files.find((file) => file.file_id === "file-004").source_available).toBe(false);
    expect(files.find((file) => file.file_id === "file-005").capability_status).toBe("keyword_only");
    await expect(adapter.getEvidence("file-004", "version-004-v1")).rejects.toMatchObject({ status: 404, code: "SOURCE_UNAVAILABLE" });
  });

  it("returns a keyword result that can be expanded by chunk id", async () => {
    const adapter = createMockAdapter(mockData, { latency: 0 });
    const payload = await adapter.search("team11-demo-09", "root-demo-01");
    expect(payload.effective_mode).toBe("keyword");
    expect(payload.results[0]).toMatchObject({
      file_id: "file-009",
      version_id: "version-009-v1",
      file_name: "team11-demo-09.pdf",
    });
    const evidence = await adapter.getEvidenceByChunk(payload.results[0].chunk_id);
    expect(evidence[0]).toMatchObject({
      file_id: "file-009",
      version_id: "version-009-v1",
      page: 1,
    });
  });
});
