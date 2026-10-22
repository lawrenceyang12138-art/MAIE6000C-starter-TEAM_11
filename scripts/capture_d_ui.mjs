// Historical 10.16 browser evidence was captured before canonical search wiring.
// For the current UI run capture_d_1019.mjs; keep the original evidence immutable.
// Browser contract fixtures only. Never use these screenshots as real backend
// acceptance evidence. Prefer an already-started API-mode production preview.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import data from "../frontend/src/mock/data.json" with { type: "json" };

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "frontend/package.json"));
const { chromium } = require(process.env.D_PLAYWRIGHT_MODULE || "playwright-core");
const baseUrl = process.env.D_UI_URL || "http://127.0.0.1:5173";
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseUrl).hostname), "Use a local frontend only");
const output = path.join(repo, "work/d-legacy-contract-recheck");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.D_BROWSER_EXECUTABLE ? { executablePath: process.env.D_BROWSER_EXECUTABLE } : { channel: "chrome" }) });
const viewport = { width: 1440, height: 1000 };
const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
page.setDefaultTimeout(15000);
const report = { evidence_type: "browser_http_contract_fixture_not_product", product_acceptance: false,
  started_at: new Date().toISOString(), base_url: baseUrl, browser_version: browser.version(), viewport, cases: [] };
let rootReads = 0;
let postCount = 0;
let evidenceReads = 0;
let scenario = "normal";
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

await page.route(new URL("/api/**", baseUrl).href, async (route) => {
  const url = new URL(route.request().url());
  const endpoint = url.pathname.replace(/^\/api/, "");
  let payload;
  let status = 200;
  if (endpoint === "/mounts") {
    if (scenario === "api-error") { status = 503; payload = { detail: "C:\\private\\source.txt traceback must not be rendered" }; }
    else payload = data.mounts;
  }
  else if (endpoint.endsWith("/directories")) payload = [{ relative_path: ".", label: "Full synthetic fixture corpus" }];
  else if (endpoint === "/roots" && route.request().method() === "POST") {
    assert.deepEqual(route.request().postDataJSON(), { mount_id: data.mounts[0].mount_id, relative_path: "." });
    postCount += 1;
    status = 202;
    payload = { root_id: data.root.root_id, job_id: "job-contract-1016", status: "pending" };
  } else if (endpoint.startsWith("/jobs/")) payload = { job_id: "job-contract-1016", root_id: data.root.root_id, status: "completed", attempts: 1 };
  else if (endpoint.startsWith("/roots/")) {
    rootReads += 1;
    payload = { root_id: data.root.root_id, status: "active", availability: "available", file_counts: scenario === "unknown-counts" ? undefined : rootReads === 1
      ? { total: 16, basic_ready: 2, enriched: 0, failed: 0, unsupported: 0 }
      : { total: 16, basic_ready: 12, enriched: 0, failed: 3, unsupported: 1 } };
  } else if (endpoint === "/files") payload = url.searchParams.get("root_id") === "root-empty-01" ? [] : data.files;
  else if (endpoint === "/search") {
    const request = route.request().postDataJSON();
    const file = data.files.find((item) => item.display_name === request.query);
    const passage = file && data.evidence[`${file.file_id}:${file.version_id}`]?.[0];
    payload = { query: request.query, mode: request.mode, effective_mode: "keyword", degraded: false,
      total: passage ? 1 : 0, results: passage ? [{ root_id: file.root_id, file_id: file.file_id, file_name: file.display_name,
        file_path: file.relative_path, version_id: file.version_id, chunk_id: passage.evidence_id, ordinal: 1,
        page: passage.page, text: passage.excerpt, reason: "Synthetic keyword match", score: 1, keyword_score: 1, semantic_score: 0 }] : [] };
  } else if (endpoint.startsWith("/evidence/")) {
    evidenceReads += 1;
    const chunkId = decodeURIComponent(endpoint.split("/")[2]);
    const passage = Object.values(data.evidence).flat().find((item) => item.evidence_id === chunkId);
    const file = data.files.find((item) => item.file_id === passage?.file_id);
    payload = { chunk_id: chunkId, file_id: file.file_id, version_id: file.version_id, relative_path: file.relative_path,
      ordinal: 1, page_number: passage.page, text: passage.excerpt, content_sha256: passage.content_sha256 };
  }
  else if (endpoint.endsWith("/evidence")) {
    evidenceReads += 1;
    const fileId = decodeURIComponent(endpoint.split("/")[2]);
    const versionId = url.searchParams.get("version_id");
    if (fileId === "file-004") { status = 404; payload = { code: "SOURCE_UNAVAILABLE" }; }
    else payload = data.evidence[`${fileId}:${versionId}`] || [];
  } else { status = 404; payload = { code: "NOT_FOUND" }; }
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
});

async function capture(name) {
  assert.equal(await page.locator(".mode-api").count(), 1, "Start Vite with VITE_DATA_MODE=api");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "Desktop layout must not overflow horizontally");
  await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
  await page.evaluate(() => {
    const watermark = document.createElement("div");
    watermark.textContent = "HTTP CONTRACT FIXTURE — NOT PRODUCT EVIDENCE";
    Object.assign(watermark.style, { position: "fixed", zIndex: "99999", bottom: "8px", left: "250px", background: "#7f1d1d", color: "white", padding: "8px 12px", font: "bold 13px sans-serif" });
    document.body.append(watermark);
  });
  await page.screenshot({ path: path.join(output, `${name}.png`) });
  report.cases.push({ name, status: "passed", screenshot: `${name}.png` });
}

try {
  await page.goto(`${baseUrl}/select`);
  await page.locator("#directory").selectOption(".");
  await capture("authorization-contract");
  await page.getByRole("button", { name: "Authorize and start scan" }).click();
  await page.getByText("14 files still awaiting processing.", { exact: false }).waitFor();
  await page.getByRole("progressbar").waitFor();
  await page.waitForFunction(() => document.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") === "100");
  assert.ok(rootReads >= 2, "A completed scan must not stop file-stage polling early");
  assert.equal(postCount, 1);
  await capture("progress-contract-12-3-1");

  await page.goto(`${baseUrl}/results/root-empty-01`);
  await page.getByText("No indexed files yet").waitFor();
  await capture("state-empty-contract");

  for (const [name, filename, text] of [
    ["state-failed-contract", "empty.pdf", "No page evidence is available for this file."],
    ["state-source-unavailable-contract", "team11-demo-04.pdf", "Cached passage hidden until the source is verified."],
    ["state-keyword-only-contract", "team11-demo-05.pdf", "Keyword-only mode · semantic enrichment unavailable"],
  ]) {
    await page.goto(`${baseUrl}/results/${data.root.root_id}`);
    await page.locator(".file-row").first().waitFor();
    await page.getByRole("textbox", { name: "Filter loaded files" }).fill(filename);
    await page.waitForFunction(() => document.querySelectorAll(".file-row").length === 1);
    if (name === "state-keyword-only-contract") {
      await page.getByRole("textbox", { name: "Search query", exact: true }).fill(filename);
      await page.getByRole("button", { name: "Search", exact: true }).click();
      await page.getByRole("heading", { name: "Search results", exact: true }).waitFor();
    }
    const readsBeforeSelection = evidenceReads;
    await page.locator(".file-row").filter({ hasText: filename }).locator(".file-row-main").click();
    await page.locator(".inspector-pane").getByText(text, { exact: true }).waitFor();
    if (name === "state-keyword-only-contract") {
      await page.locator(".inspector-pane .evidence-record").waitFor();
      assert.equal(evidenceReads, readsBeforeSelection + 1, "Keyword evidence remains available in the fixture");
    } else {
      assert.equal(await page.locator(".inspector-pane .evidence-record").count(), 0);
      assert.equal(evidenceReads, readsBeforeSelection, "Do not fetch evidence for known invalid or zero-page sources");
    }
    await capture(name);
  }

  scenario = "unknown-counts";
  await page.goto(`${baseUrl}/scan/job-contract-1016`);
  await page.getByText("File counters unavailable. No readiness is inferred from scan status.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("progressbar").count(), 0, "Unknown counters must not imply 100% readiness");
  assert.equal(await page.locator(".job-stats strong").allTextContents().then((items) => items.every((value) => value.includes("—"))), true);
  await capture("state-unknown-counts-contract");

  scenario = "api-error";
  await page.goto(`${baseUrl}/select`);
  await page.getByRole("alert").filter({ hasText: "HTTP_503" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Authorize and start scan" }).isDisabled(), true);
  assert.equal(await page.locator("body").innerText().then((value) => /private|traceback/.test(value)), false, "Backend details must stay hidden");
  assert.equal(await page.locator(".mode-mock").count(), 0, "An API failure must not silently switch to Mock");
  await capture("state-api-error-contract");

  assert.deepEqual(pageErrors, [], "Browser runtime errors must be resolved before accepting screenshots");
  assert.equal(postCount, 1, "Read retries and navigation must not replay authorization");
  report.status = "passed";
  console.log(`Browser contract fixtures: ${report.cases.length} passed; product acceptance: false`);
} catch (error) {
  report.status = "failed";
  report.error = error.message;
  process.exitCode = 1;
} finally {
  Object.assign(report, { completed_at: new Date().toISOString(), page_errors: pageErrors, authorization_posts: postCount, root_reads: rootReads, evidence_reads: evidenceReads });
  fs.writeFileSync(path.join(output, "browser-contract-report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
}
