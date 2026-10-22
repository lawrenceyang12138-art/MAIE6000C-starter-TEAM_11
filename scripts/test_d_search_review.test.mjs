import assert from "node:assert/strict";
import { test } from "node:test";
import { createApiAdapter } from "../frontend/src/api/http-adapter.js";
import { createMockAdapter } from "../frontend/src/api/mock-adapter.js";
import { createAdapter } from "../frontend/src/api/adapter.js";
import { evidenceMatchesHit } from "../frontend/src/lib/search.js";
import { isSourceUnavailable } from "../frontend/src/lib/scan.js";
import data from "../frontend/src/mock/data.json" with { type: "json" };
import relationData from "../frontend/src/mock/relations.json" with { type: "json" };

const hit = { root_id: "root", file_id: "file", file_name: "manual.pdf", file_path: "docs/manual.pdf",
  version_id: "version", chunk_id: "chunk", ordinal: 2, page: 3, text: "Database backup",
  reason: "keyword: backup", score: 0.9, keyword_score: 1, semantic_score: 0 };
const response = { query: "backup", mode: "hybrid", effective_mode: "keyword", degraded: true,
  degradation_reason: "ai_disabled", total: 1, results: [hit] };
const evidence = { chunk_id: "chunk", file_id: "file", version_id: "version", relative_path: hit.file_path,
  page_number: 3, ordinal: 2, text: "Database backup", content_sha256: "a".repeat(64) };
const relation = { relationship_id: "rel", entity_type: "topic", label: "Database", relation_type: "mentions",
  page_number: 3, quote: "Database backup", evidence_missing: false, decision: null, decision_revision: 0, corrected_entity_id: null };
const apiWith = (payload, status = 200) => createApiAdapter({ fetchImpl: async () => new Response(JSON.stringify(payload), { status }) });

test("search posts canonical scope/mode and preserves explicit keyword degradation", async () => {
  let sent;
  const api = createApiAdapter({ fetchImpl: async (url, options) => {
    sent = { url, method: options.method, body: JSON.parse(options.body) };
    return new Response(JSON.stringify(response));
  } });
  assert.equal((await api.search({ query: "backup", rootId: "root", fileId: "file" })).effective_mode, "keyword");
  assert.deepEqual(sent, { url: "/api/search", method: "POST", body: { query: "backup", mode: "hybrid", top_k: 10, root_id: "root", file_id: "file" } });
});

test("empty search is a valid success, while HTTP 503 remains an error", async () => {
  assert.deepEqual((await apiWith({ ...response, total: 0, results: [] }).search({ query: "backup" })).results, []);
  await assert.rejects(apiWith({ detail: "private traceback" }, 503).search({ query: "backup" }), { code: "HTTP_503" });
});

for (const [name, changed] of [
  ["wrong root", { ...hit, root_id: "other" }], ["wrong file filter", { ...hit, file_id: "other" }],
  ["absolute path", { ...hit, file_path: "C:\\private.pdf" }], ["invalid page", { ...hit, page: 0 }],
  ["invalid score", { ...hit, score: 1.1 }], ["missing chunk", { ...hit, chunk_id: "" }],
]) test(`search rejects ${name}`, async () => {
  await assert.rejects(apiWith({ ...response, results: [changed] }).search({ query: "backup", rootId: "root", fileId: "file" }), { code: "CONTRACT_MISMATCH" });
});

test("search rejects duplicated files and silent mode changes", async () => {
  await assert.rejects(apiWith({ ...response, total: 2, results: [hit, hit] }).search({ query: "backup" }), { code: "CONTRACT_MISMATCH" });
  await assert.rejects(apiWith({ ...response, degraded: false }).search({ query: "backup" }), { code: "CONTRACT_MISMATCH" });
});

test("chunk evidence uses canonical route and matches file/version/page/ordinal/path", async () => {
  let requested;
  const api = createApiAdapter({ fetchImpl: async (url) => { requested = url; return new Response(JSON.stringify({ ...evidence, chunk_id: "chunk/a" })); } });
  await api.getEvidenceByChunk("chunk/a");
  assert.equal(requested, "/api/evidence/chunk%2Fa");
  assert.equal(evidenceMatchesHit(evidence, hit), true);
  for (const field of ["chunk_id", "file_id", "version_id", "page_number", "ordinal", "relative_path"]) {
    assert.equal(evidenceMatchesHit({ ...evidence, [field]: "wrong" }, hit), false, field);
  }
});

test("lowercase source refusals suppress cached source text", async () => {
  for (const code of ["version_superseded", "file_missing", "root_revoked", "chunk_not_found", "no_current_version"]) {
    await assert.rejects(apiWith({ detail: { code, message: "C:\\private traceback" } }, 409).getEvidenceByChunk("chunk"), (error) =>
      error.code === code && !error.message.includes("private") && isSourceUnavailable({}, error));
  }
  assert.equal(isSourceUnavailable({ presence_status: "missing", status: "basic_ready" }), true);
});

test("canonical integer jobs work without accepting the starter job envelope", async () => {
  const accepted = await apiWith({ root_id: "root", job_id: 17, status: "pending" }, 202).createRootScan("mount", ".");
  assert.equal(accepted.job_id, 17);
  assert.equal((await apiWith({ root_id: "root", job_id: 17, status: "running" }).getJob("17")).status, "running");
  await assert.rejects(apiWith({ id: 17, status: "claimed" }).getJob("17"));
});

test("failed job retry posts once and requires the same job/root in a 202 pending receipt", async () => {
  let sent;
  const api = createApiAdapter({ fetchImpl: async (url, options) => {
    sent = { url, method: options.method, body: options.body ?? null };
    return new Response(JSON.stringify({ job_id: "job/17", root_id: "root", status: "pending" }), { status: 202 });
  } });
  const accepted = await api.retryJob("job/17", "root");
  assert.deepEqual(sent, { url: "/api/jobs/job%2F17/retry", method: "POST", body: null });
  assert.deepEqual(accepted, { job_id: "job/17", root_id: "root", status: "pending", status_code: 202 });
  for (const payload of [
    { job_id: "other", root_id: "root", status: "pending" },
    { job_id: "job/17", root_id: "other", status: "pending" },
    { job_id: "job/17", root_id: "root", status: "running" },
  ]) await assert.rejects(apiWith(payload, 202).retryJob("job/17", "root"), { code: "CONTRACT_MISMATCH" });
  await assert.rejects(apiWith({ job_id: "job/17", root_id: "root", status: "pending" }, 200).retryJob("job/17", "root"), { code: "CONTRACT_MISMATCH" });
});

test("mock failed-job retry keeps identity and returns the same job to pending", async () => {
  const failedData = structuredClone(data);
  const base = failedData.progress_sequence[0];
  failedData.progress_sequence = [
    { ...base, status: "failed" },
    { ...base, status: "completed" },
  ];
  const mock = createMockAdapter(failedData, { latency: 0 });
  const created = await mock.createRootScan("mount-team11-demo", "normal");
  assert.equal((await mock.getJob(created.job_id)).status, "failed");
  assert.deepEqual(await mock.retryJob(created.job_id, created.root_id), {
    status_code: 202, job_id: created.job_id, root_id: created.root_id, status: "pending",
  });
  assert.equal((await mock.getJob(created.job_id)).status, "pending");
  assert.equal((await mock.getJob(created.job_id)).attempts, 2);
  await assert.rejects(mock.retryJob(created.job_id, "wrong-root"), { status: 404, code: "UNKNOWN_JOB" });
});

test("unprocessed files can have a null version", async () => {
  const files = await apiWith([{ root_id: "root", file_id: "file", version_id: null, display_name: "manual.pdf", relative_path: "manual.pdf", status: "discovered" }]).listFiles("root");
  assert.equal(files[0].version_id, null);
  const failed = { root_id: "root", file_id: "file", version_id: "version", display_name: "manual.pdf", relative_path: "manual.pdf", status: "unsupported", error_code: "no_text_layer" };
  assert.equal((await apiWith([failed]).listFiles("root"))[0].error_code, "no_text_layer");
});

test("relation collection stays bounded and preserves unreviewed candidates", async () => {
  assert.equal((await apiWith([relation]).listRelations("version"))[0].decision, null);
  await assert.rejects(apiWith(Array.from({ length: 21 }, (_, index) => ({ ...relation, relationship_id: String(index) }))).listRelations("version"));
});

test("reviews post expected revision, correction target and reviewer without replay", async () => {
  const calls = [];
  const api = createApiAdapter({ fetchImpl: async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return new Response(JSON.stringify({ decision_revision: 3 }));
  } });
  await api.recordReview("rel/a", { decision: "corrected", expectedRevision: 2, actor: "D", reason: "wrong name", correctedEntityId: "entity" });
  assert.deepEqual(calls, [{ url: "/api/relations/rel%2Fa/reviews", body: { decision: "corrected", expected_revision: 2, actor: "D", reason: "wrong name", corrected_entity_id: "entity" } }]);
  await assert.rejects(api.recordReview("rel", { decision: "corrected", expectedRevision: 2, actor: "D" }));
  await assert.rejects(api.recordReview("rel", { decision: "confirmed", expectedRevision: 2, actor: "D", correctedEntityId: "entity" }));
  assert.equal(calls.length, 1);
});

test("revision conflict is distinct and no review is retried automatically", async () => {
  let calls = 0;
  const api = createApiAdapter({ fetchImpl: async () => {
    calls += 1;
    return new Response(JSON.stringify({ detail: { code: "review_conflict" } }), { status: 409 });
  } });
  await assert.rejects(api.recordReview("rel", { decision: "rejected", expectedRevision: 0, actor: "D" }), { code: "review_conflict" });
  assert.equal(calls, 1);
});

test("explicit mock search reports keyword simulation and resolves its version-bound chunk", async () => {
  const mock = createMockAdapter(data, { latency: 0 });
  const result = await mock.search({ query: "team11-demo-01", rootId: data.root.root_id, mode: "hybrid" });
  assert.equal(result.degradation_reason, "mock_keyword_only");
  assert.equal(result.results.length, 1);
  const source = await mock.getEvidenceByChunk(result.results[0].chunk_id);
  assert.equal(evidenceMatchesHit(source, result.results[0]), true);
  assert.deepEqual(await mock.listRelations(data.files[0].version_id), []);
  const sample = createMockAdapter(relationData, { latency: 0 });
  const accepted = await sample.createRootScan("mount-relations-demo", "sample");
  assert.equal(accepted.root_id, "root-relations-demo");
  const candidates = await sample.listRelations("version-relations-demo-v1");
  assert.equal(candidates.length, 3);
  assert.equal((await sample.search({ query: candidates[0].quote, rootId: accepted.root_id, mode: "keyword" })).results.length, 1);
  await sample.recordReview("relation-person", { decision: "confirmed", expectedRevision: 0 });
  await assert.rejects(sample.recordReview("relation-person", { decision: "rejected", expectedRevision: 0 }), { code: "review_conflict" });
  assert.equal((await sample.listRelations("version-relations-demo-v1"))[0].decision, "confirmed");
  await assert.rejects(sample.recordReview("relation-project", { decision: "corrected", expectedRevision: 0, correctedEntityId: "invented-entity" }), { code: "corrected_entity_not_found" });
  await sample.recordReview("relation-project", { decision: "corrected", expectedRevision: 0, correctedEntityId: "entity-replacement" });
  await sample.recordReview("relation-topic", { decision: "rejected", expectedRevision: 0 });
  assert.deepEqual((await sample.listRelations("version-relations-demo-v1")).map((item) => item.decision), ["confirmed", "corrected", "rejected"]);
  assert.equal(createAdapter({ mode: "mock", scenario: "relations" }).mode, "mock");
  assert.throws(() => createAdapter({ mode: "mock", scenario: "relation-typo" }), /VITE_MOCK_SCENARIO/);
  assert.equal(createAdapter({ mode: "api", scenario: "relation-typo" }).mode, "api");
});
