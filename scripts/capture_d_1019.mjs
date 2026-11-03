// Browser acceptance of D's HTTP consumer contract only, never product acceptance.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "frontend/package.json"));
const { chromium } = require(process.env.D_PLAYWRIGHT_MODULE || "playwright-core");
const baseUrl = process.env.D_UI_URL || "http://127.0.0.1:5173";
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseUrl).hostname));
const output = process.env.D_UI_OUTPUT ? path.resolve(repo, process.env.D_UI_OUTPUT) : path.join(repo, "submissions/week07/evidence/1019-D");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.D_BROWSER_EXECUTABLE ? { executablePath: process.env.D_BROWSER_EXECUTABLE } : { channel: "chrome" }) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
page.setDefaultTimeout(10000);
const quote = "Dr Chen leads the Atlas Project on Database Reliability.";
const file = { root_id: "root-contract", file_id: "file-contract", version_id: "version-contract", display_name: "contract-example.pdf", relative_path: "examples/contract-example.pdf", presence_status: "present", status: "basic_ready" };
const hit = { root_id: file.root_id, file_id: file.file_id, file_name: file.display_name, file_path: file.relative_path,
  version_id: file.version_id, version_created_at: "2026-10-19T00:00:00Z", chunk_id: "chunk-contract", ordinal: 1,
  page: 2, text: quote, reason: "keyword: database", score: 0.9, keyword_score: 1, semantic_score: 0 };
let relations = [["person", "Chen"], ["project", "Atlas Project"], ["topic", "Database Reliability"]].map(([entity_type, label], index) => ({ entity_id: "entity-" + index, chunk_id: hit.chunk_id, relationship_id: "rel-" + index, entity_type, label, relation_type: "mentions", kind: "source_supported", origin: "rule", producer_revision: "rules-contract-v1", page_number: 2, quote, evidence_missing: false, decision: null, decision_revision: 0, corrected_entity_id: null }));
const evidence = { chunk_id: hit.chunk_id, file_id: file.file_id, version_id: file.version_id,
  relative_path: file.relative_path, page_number: 2, ordinal: 1, text: quote, content_sha256: "a".repeat(64) };
const errors = [], searches = [], writes = [], scans = [], cases = [];
const retryJobId = "job-retry-contract";
const retryPosts = [];
let retryAccepted = false;
let scenario = "normal";
page.on("pageerror", (error) => errors.push(error.message));
await page.addInitScript(() => sessionStorage.setItem("lastRootId", "root-contract"));
await page.route(new URL("/api/**", baseUrl).href, async (route) => {
  const url = new URL(route.request().url());
  const endpoint = url.pathname.replace(/^\/api/, "");
  let body, status = 200;
  if (endpoint === "/files") body = [file];
  else if (endpoint === `/roots/${file.root_id}/scans` && route.request().method() === "POST") {
    scans.push({ method: route.request().method(), endpoint, body: route.request().postData() });
    status = 202;
    body = { root_id: file.root_id, job_id: "job-rescan-contract", status: "pending" };
  } else if (endpoint === `/jobs/${retryJobId}/retry` && route.request().method() === "POST") {
    retryPosts.push({ method: route.request().method(), endpoint, body: route.request().postData() });
    retryAccepted = true;
    status = 202;
    body = { job_id: retryJobId, root_id: file.root_id, status: "pending" };
  } else if (endpoint === `/jobs/${retryJobId}`) {
    body = { job_id: retryJobId, root_id: file.root_id, status: retryAccepted ? "pending" : "failed",
      attempts: retryAccepted ? 2 : 1, error_code: retryAccepted ? null : "JOB_FAILED" };
  } else if (endpoint === "/jobs/job-rescan-contract") {
    body = { job_id: "job-rescan-contract", root_id: file.root_id, status: "completed", attempts: 1, error_code: null };
  } else if (endpoint === `/roots/${file.root_id}`) {
    body = { root_id: file.root_id, status: "active", availability: "available",
      file_counts: { total: 1, basic_ready: 1, enriched: 0, failed: 0, unsupported: 0 } };
  } else if (endpoint === "/search") {
    const request = route.request().postDataJSON(); searches.push(request);
    assert.equal(request.root_id, file.root_id);
    if (scenario === "search-error") { status = 503; body = { detail: "private traceback" }; }
    else body = { query: request.query, mode: request.mode, effective_mode: "keyword", degraded: request.mode !== "keyword",
      degradation_reason: request.mode !== "keyword" ? "ai_disabled" : null, total: request.query === "no-match" ? 0 : 1,
      results: request.query === "no-match" ? [] : [hit] };
  } else if (endpoint.startsWith("/evidence/")) {
    if (scenario === "stale") { status = 409; body = { detail: { code: "version_superseded", message: "private path" } }; }
    else if (scenario === "source-error") { status = 503; body = { detail: "private traceback" }; }
    else body = evidence;
  } else if (endpoint.endsWith("/relations")) {
    if (scenario === "relation-error") { status = 404; body = { detail: "missing route" }; }
    else body = relations;
  } else if (endpoint.endsWith("/reviews")) {
    const request = route.request().postDataJSON(); writes.push(request);
    const relation = relations.find((item) => endpoint.includes(item.relationship_id));
    if (scenario === "conflict") { relation.decision = "rejected"; relation.decision_revision += 1; status = 409; body = { detail: { code: "review_conflict" } }; }
    else {
      assert.equal(request.expected_revision, relation.decision_revision);
      relation.decision_revision += 1; relation.decision = request.decision;
      relation.corrected_entity_id = request.corrected_entity_id || null;
      body = { relationship_id: relation.relationship_id, decision: request.decision, decision_revision: relation.decision_revision };
    }
  } else { status = 404; body = { detail: { code: "not_found" } }; }
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
});

async function capture(name) {
  assert.equal(await page.locator(".mode-api").count(), 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Viewport overflow: " + name);
  await page.evaluate(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    document.querySelector("#contract-watermark")?.remove();
    const mark = document.createElement("div"); mark.id = "contract-watermark";
    mark.textContent = "HTTP CONTRACT FIXTURE - NOT PRODUCT ACCEPTANCE";
    Object.assign(mark.style, { position: "absolute", zIndex: 99999, top: "0", left: "0", maxWidth: "95vw", padding: "4px 8px", background: "#7f1d1d", color: "white", font: "bold 11px sans-serif", pointerEvents: "none" });
    document.body.append(mark);
  });
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true });
  cases.push({ name, status: "passed" });
}
async function search(query, mode = "keyword") {
  await page.getByLabel("Search query", { exact: true }).fill(query);
  await page.getByLabel("Search mode", { exact: true }).selectOption(mode);
  await page.getByRole("button", { name: "Search", exact: true }).click();
}
async function reviewCard(label, decision) {
  const card = page.locator(".relation-card").filter({ has: page.getByRole("heading", { name: label, exact: true }) });
  await card.getByRole("button", { name: "Open source passage", exact: true }).click();
  await card.getByText("Source verified", { exact: false }).waitFor();
  await card.getByLabel("Reviewer", { exact: true }).fill("contract-reviewer");
  await card.getByLabel("Decision for " + label, { exact: true }).selectOption(decision);
  if (decision === "corrected") await card.getByLabel("Replacement entity for " + label, { exact: true }).selectOption("entity-0");
  await card.getByRole("button", { name: "Save decision", exact: true }).click();
  return card;
}
let passed = false;
try {
  await page.goto(baseUrl + "/results/" + file.root_id);
  await search("database");
  await page.locator(".file-row").filter({ hasText: "MATCH REASON" }).waitFor();
  await page.locator(".file-row-main").click();
  await page.locator(".inspector-pane .evidence-record").waitFor();
  await capture("keyword-evidence");
  await search("database", "hybrid");
  await page.getByText("Reduced search capability", { exact: true }).waitFor();
  await capture("keyword-fallback");
  await search("no-match"); await page.getByText("No matches found", { exact: true }).waitFor();
  await capture("empty-search");
  scenario = "search-error"; await search("database");
  await page.getByRole("alert").filter({ hasText: "HTTP_503" }).waitFor();
  await capture("search-error");
  scenario = "normal"; await page.getByRole("button", { name: "Retry search", exact: true }).click();
  await page.locator(".file-row-main").waitFor();
  scenario = "stale"; await page.locator(".file-row-main").click();
  await page.getByRole("alert").filter({ hasText: "version_superseded" }).waitFor();
  assert.equal(await page.locator(".inspector-pane .evidence-record").count(), 0);
  assert.equal(await page.locator(".file-row-details").innerText().then((value) => value.includes(quote)), false);
  await capture("stale-evidence");

  scenario = "normal"; await page.goto(baseUrl + "/graph");
  await page.locator(".relation-card").first().waitFor();
  assert.equal(await page.locator(".relation-card").count(), 3);
  await page.locator(".relation-card").first().getByRole("button", { name: "Open source passage", exact: true }).click();
  await page.getByText("Source verified", { exact: false }).waitFor();
  await capture("relation-candidates");
  await page.goto(baseUrl + "/review");
  const sourceCard = page.locator(".relation-card").first();
  await sourceCard.waitFor();
  assert.ok((await sourceCard.locator("blockquote").innerText()).startsWith("Unverified candidate quote:"));
  scenario = "source-error";
  await sourceCard.getByRole("button", { name: "Open source passage", exact: true }).click();
  await sourceCard.getByRole("alert").filter({ hasText: "HTTP_503" }).waitFor();
  assert.equal((await sourceCard.locator("blockquote").innerText()).includes(quote), false);
  assert.equal(await sourceCard.getByRole("button", { name: "Save decision", exact: true }).isDisabled(), true);
  assert.equal(writes.length, 0);
  await capture("review-source-unavailable");
  scenario = "normal";
  await sourceCard.getByRole("button", { name: "Open source passage", exact: true }).click();
  await sourceCard.getByText("Source verified", { exact: false }).waitFor();
  assert.equal(await sourceCard.locator("fieldset").isEnabled(), true);
  assert.ok((await sourceCard.locator("blockquote").innerText()).startsWith("Verified candidate quote:"));
  await capture("review-source-recovered");
  await page.reload();
  for (const [label, decision] of [["Chen", "confirmed"], ["Atlas Project", "corrected"], ["Database Reliability", "rejected"]]) {
    const card = await reviewCard(label, decision);
    await card.getByText("Decision saved by service", { exact: false }).waitFor();
  }
  assert.deepEqual(writes.map((item) => item.decision), ["confirmed", "corrected", "rejected"]);
  assert.equal(writes[1].corrected_entity_id, "entity-0");
  await capture("review-decisions");
  await page.reload();
  scenario = "conflict";
  const conflictCard = await reviewCard("Chen", "rejected");
  await conflictCard.getByRole("alert").filter({ hasText: "review_conflict" }).waitFor();
  assert.equal(await conflictCard.getByRole("button", { name: "Save decision", exact: true }).isDisabled(), true);
  await capture("review-conflict");
  await conflictCard.getByRole("button", { name: "Reload latest candidates", exact: true }).click();
  await page.locator(".relation-card").first().getByText("Revision 2", { exact: false }).waitFor();
  assert.equal(writes.length, 4);
  scenario = "relation-error"; await page.reload();
  await page.getByRole("alert").filter({ hasText: "HTTP_404" }).waitFor();
  assert.equal(await page.locator(".relation-card").count(), 0);
  await capture("relation-endpoint-unavailable");

  scenario = "normal";
  for (const width of [375, 768, 1024]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(baseUrl + "/results/" + file.root_id);
    await search("database"); await page.locator(".file-row-main").waitFor();
    await capture("search-width-" + width);
    await page.goto(baseUrl + "/review"); await page.locator(".relation-card").first().waitFor();
    await capture("review-width-" + width);
  }
  await page.goto(baseUrl + "/results/" + file.root_id);
  await page.getByRole("button", { name: "Rescan directory", exact: true }).click();
  await page.getByRole("heading", { name: "Scan progress", exact: true }).waitFor();
  await page.locator(".page-heading .lede").filter({ hasText: "Job job-rescan-contract" }).waitFor();
  assert.deepEqual(scans, [{ method: "POST", endpoint: "/roots/root-contract/scans", body: null }]);
  await capture("rescan-accepted");
  await page.goto(baseUrl + "/scan/" + retryJobId);
  await page.getByText("Last read status failed", { exact: false }).waitFor();
  await page.getByRole("button", { name: "Retry failed job", exact: true }).click();
  await page.getByText("Last read status pending", { exact: false }).waitFor();
  assert.deepEqual(retryPosts, [{ method: "POST", endpoint: `/jobs/${retryJobId}/retry`, body: null }]);
  await capture("retry-job-accepted");
  assert.deepEqual(errors, []);
  assert.equal(await page.locator("body").innerText().then((value) => /private|traceback/.test(value)), false);
  passed = true;
} finally {
  fs.writeFileSync(path.join(output, "browser-contract-report.json"), JSON.stringify({
    status: passed ? "passed" : "failed", observed_at: new Date().toISOString(),
    evidence_type: "browser_http_contract_fixture_not_product", product_acceptance: false,
    git_head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim(),
    source_sha256: Object.fromEntries(["frontend/src/app.jsx", "frontend/src/relations-page.jsx", "frontend/src/rescan-control.jsx", "frontend/src/retry-job-control.jsx", "frontend/src/api/adapter.js", "frontend/src/api/http-adapter.js", "frontend/src/api/mock-adapter.js", "frontend/src/mock/relations.json", "frontend/src/lib/search.js", "frontend/src/lib/use-search.js", "frontend/src/styles.css"].map((name) =>
      [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(repo, name))).digest("hex")])),
    browser: browser.version(), cases, page_errors: errors, search_requests: searches.length, review_posts: writes, rescan_posts: scans, retry_posts: retryPosts,
  }, null, 2) + "\n");
  await browser.close();
}
console.log(`D 10.19 browser contract checks: ${cases.length} passed; product acceptance: false.`);
