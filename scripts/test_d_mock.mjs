import assert from "node:assert/strict";
import mockData from "../frontend/src/mock/data.json" with { type: "json" };
import { AdapterError } from "../frontend/src/api/errors.js";
import { createMockAdapter } from "../frontend/src/api/mock-adapter.js";

const adapter = createMockAdapter(mockData, { latency: 0 });

const accepted = await adapter.createRootScan("mount-team11-demo", "normal");
assert.deepEqual(
  { status_code: accepted.status_code, root_id: accepted.root_id, status: accepted.status },
  { status_code: 202, root_id: "root-demo-01", status: "pending" },
);
const first = await adapter.getJob(accepted.job_id);
const second = await adapter.getJob(accepted.job_id);
const third = await adapter.getJob(accepted.job_id);
const fourth = await adapter.getJob(accepted.job_id);
assert.equal(first.status, "pending");
assert.equal(second.status, "running");
assert.equal(third.processed, 12);
assert.equal(fourth.status, "completed");

const files = await adapter.listFiles(accepted.root_id);
assert.equal(files.length, 16);
assert.equal(files.filter((file) => file.status === "basic_ready").length, 12);
assert.equal(files.filter((file) => file.status === "failed").length, 3);
assert.equal(files.filter((file) => file.status === "unsupported").length, 1);

const evidence = await adapter.getEvidence("file-009", "version-009-v1");
assert.equal(evidence.length, 3);
assert.equal(evidence[2].page, 3);

const empty = createMockAdapter(mockData, { latency: 0 });
const emptyAccepted = await empty.createRootScan("mount-team11-demo", "empty");
assert.deepEqual(await empty.listFiles(emptyAccepted.root_id), []);
await empty.getJob(emptyAccepted.job_id);
assert.equal((await empty.getJob(emptyAccepted.job_id)).status, "completed");

await assert.rejects(
  () => adapter.createRootScan("mount-team11-demo", "../outside"),
  (error) => error instanceof AdapterError && error.code === "PATH_OUT_OF_SCOPE",
);
await assert.rejects(
  () => adapter.getEvidence("file-004", "version-004-v1"),
  (error) => error instanceof AdapterError && error.code === "SOURCE_UNAVAILABLE",
);

console.log("Mock adapter checks passed: 202 contract, progress, 16-file inventory, empty directory, evidence, and failure states.");
