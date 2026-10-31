// Real W7 browser workflow. No HTTP interception or injected application data.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values: options } = parseArgs({ options: {
  ui: { type: "string", default: "http://127.0.0.1:3000" },
  mount: { type: "string", default: "corpus" },
  directory: { type: "string", default: "." },
  query: { type: "string", default: "invoices" },
  "expected-files": { type: "string", default: "16" },
  "expected-unsupported": { type: "string", default: "4" },
  "relations-mount": { type: "string", default: "relations" },
  "relations-directory": { type: "string", default: "." },
  "skip-relations": { type: "boolean", default: false },
  output: { type: "string", default: "work/w7-browser" },
  help: { type: "boolean", default: false },
} });
if (options.help) {
  console.log("node scripts/verify_w7_browser.mjs --ui http://127.0.0.1:3000 --mount corpus --directory . --query invoices --expected-files 16 --expected-unsupported 4 --relations-mount relations --relations-directory . [--skip-relations] --output work/w7-browser");
  process.exit(0);
}
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const base = new URL(options.ui);
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(base.hostname), "Use a local application URL.");
const expectedFiles = Number(options["expected-files"]);
const expectedUnsupported = Number(options["expected-unsupported"]);
assert.ok(Number.isSafeInteger(expectedFiles) && expectedFiles > 0);
assert.ok(Number.isSafeInteger(expectedUnsupported) && expectedUnsupported >= 0);
const output = path.resolve(repo, options.output);
fs.mkdirSync(output, { recursive: true });
const require = createRequire(path.join(repo, "frontend/package.json"));
const { chromium } = require(process.env.D_PLAYWRIGHT_MODULE || "playwright-core");
const browser = await chromium.launch({ headless: true, ...(process.env.D_BROWSER_EXECUTABLE
  ? { executablePath: process.env.D_BROWSER_EXECUTABLE } : { channel: "chrome" }) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
page.setDefaultTimeout(15000);
const report = { status: "running", observed_at: new Date().toISOString(),
  evidence_type: "live_browser_api_worker", http_interception: false, mock_data: false,
  request: { mount_id: options.mount, relative_path: options.directory, expected_files: expectedFiles,
    expected_unsupported: expectedUnsupported, review_workflow: !options["skip-relations"] },
  ui_url: base.origin, browser: browser.version(), cases: [], page_errors: [], requests: [] };
page.on("pageerror", (error) => report.page_errors.push(error.message));
page.on("response", (response) => {
  const url = new URL(response.url());
  if (url.pathname.startsWith("/api/")) report.requests.push({
    method: response.request().method(), path: url.pathname, status: response.status(),
  });
});
const ui = (suffix) => new URL(suffix, base).href;
const api = (suffix) => ui("/api" + suffix);
const isResponse = (suffix, method) => (response) =>
  new URL(response.url()).pathname === "/api" + suffix && response.request().method() === method;
async function read(suffix) {
  const response = await page.request.get(api(suffix));
  assert.equal(response.status(), 200, `GET ${suffix}: ${await response.text()}`);
  return response.json();
}
async function capture(name) {
  assert.equal(await page.locator(".mode-api").count(), 1, "The application must use the real API adapter.");
  assert.equal(await page.locator(".mode-mock").count(), 0);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Viewport overflow");
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true });
  report.cases.push({ name, status: "passed" });
}
async function settled(accepted) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const job = await read(`/jobs/${accepted.job_id}`);
    assert.ok(!["failed", "canceled"].includes(job.status), JSON.stringify(job));
    const root = await read(`/roots/${accepted.root_id}`);
    const counts = root.file_counts;
    if (job.status === "completed" && counts && counts.total > 0 &&
      counts.basic_ready + counts.enriched + counts.failed + counts.unsupported === counts.total) {
      return { job, root, files: await read(`/files?root_id=${accepted.root_id}`) };
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("The real scan/extraction pipeline did not settle within 120 seconds.");
}
async function authorize(mount, directory) {
  await page.goto(ui("/select"));
  await page.getByLabel("Read-only mount", { exact: true }).selectOption(mount);
  await page.getByLabel("Configured directory", { exact: true }).selectOption(directory);
  const [response] = await Promise.all([
    page.waitForResponse(isResponse("/roots", "POST")),
    page.getByRole("button", { name: "Authorize and start scan" }).click(),
  ]);
  assert.equal(response.status(), 202);
  const accepted = await response.json();
  assert.equal(accepted.status, "pending");
  await page.waitForURL(ui(`/scan/${accepted.job_id}`));
  return { accepted, ...await settled(accepted) };
}
function identities(files) {
  return files.map(({ file_id, version_id, relative_path }) => ({ file_id, version_id, relative_path }))
    .sort((a, b) => a.relative_path.localeCompare(b.relative_path));
}
try {
  report.setup = await read("/setup");
  report.import = await authorize(options.mount, options.directory);
  assert.equal(report.import.files.length, expectedFiles);
  assert.equal(report.import.root.file_counts.unsupported, expectedUnsupported);
  assert.equal(report.import.root.file_counts.failed, 0);
  await page.reload();
  await page.getByRole("progressbar", { name: "File processing progress" }).waitFor();
  await page.locator(".page-heading .status-badge").filter({ hasText: "Scan complete" }).waitFor();
  await capture("01-import-progress");
  await page.getByRole("button", { name: "View available files and evidence" }).click();
  await page.getByLabel("Search query", { exact: true }).fill(options.query);
  const [searchResponse] = await Promise.all([
    page.waitForResponse(isResponse("/search", "POST")),
    page.getByRole("button", { name: "Search", exact: true }).click(),
  ]);
  assert.equal(searchResponse.status(), 200);
  report.search = await searchResponse.json();
  assert.ok(report.search.results.length > 0, "The verification query must match a real indexed passage.");
  const [sourceResponse] = await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname.startsWith("/api/evidence/")),
    page.locator(".file-row-main").first().click(),
  ]);
  assert.equal(sourceResponse.status(), 200);
  report.evidence = await sourceResponse.json();
  assert.equal(report.evidence.chunk_id, report.search.results[0].chunk_id);
  await page.locator(".inspector-pane .evidence-record").waitFor();
  await capture("02-search-source-evidence");
  const [rescanResponse] = await Promise.all([
    page.waitForResponse(isResponse(`/roots/${report.import.accepted.root_id}/scans`, "POST")),
    page.getByRole("button", { name: "Rescan directory", exact: true }).click(),
  ]);
  assert.equal(rescanResponse.status(), 202);
  const rescan = await rescanResponse.json();
  report.rescan = { accepted: rescan, ...await settled(rescan) };
  assert.deepEqual(identities(report.rescan.files), identities(report.import.files));
  await page.waitForURL(ui(`/scan/${rescan.job_id}`));
  await page.locator(".page-heading .status-badge").filter({ hasText: "Scan complete" }).waitFor();
  await capture("03-rescan-reuses-file-versions");

  if (!options["skip-relations"]) {
    report.relation_import = await authorize(options["relations-mount"], options["relations-directory"]);
    const relationFile = report.relation_import.files.find((file) => file.relative_path.endsWith("entities.pdf"))
      || report.relation_import.files.find((file) => ["basic_ready", "enriched"].includes(file.status));
    assert.ok(relationFile, "The relation mount needs a parseable relation fixture.");
    report.relations_before = await read(`/versions/${relationFile.version_id}/relations`);
    assert.ok(report.relations_before.length >= 3, "The relation fixture needs at least three candidates.");
    await page.getByRole("button", { name: "Relations", exact: true }).click();
    await page.getByLabel("Relation document", { exact: true }).selectOption(relationFile.version_id);
    await page.locator(".relation-card").first().waitFor();
    await capture("04-real-relation-candidates");
    await page.getByRole("button", { name: "Human Review", exact: true }).click();
    await page.getByLabel("Relation document", { exact: true }).selectOption(relationFile.version_id);
    await page.locator(".relation-card").first().waitFor();
    report.reviews = [];
    for (const [index, decision] of ["confirmed", "corrected", "rejected"].entries()) {
      const relation = report.relations_before[index];
      const card = page.locator(".relation-card").nth(index);
      assert.equal(await card.getByRole("button", { name: "Save decision", exact: true }).isDisabled(), true);
      await card.getByRole("button", { name: "Open source passage", exact: true }).click();
      await card.getByText("Source verified", { exact: false }).waitFor();
      await card.getByLabel("Decision for " + relation.label, { exact: true }).selectOption(decision);
      let correctedEntityId = null;
      if (decision === "corrected") {
        correctedEntityId = report.relations_before.find((item) => item.entity_id !== relation.entity_id)?.entity_id;
        assert.ok(correctedEntityId, "The correction needs another existing entity.");
        await card.getByLabel("Replacement entity for " + relation.label, { exact: true }).selectOption(correctedEntityId);
      }
      await card.getByLabel("Reviewer", { exact: true }).fill("automated-w7-browser-check");
      await card.getByLabel("Reason", { exact: true }).fill("W7 workflow verification on the synthetic relation fixture.");
      const [receiptResponse] = await Promise.all([
        page.waitForResponse(isResponse(`/relations/${relation.relationship_id}/reviews`, "POST")),
        card.getByRole("button", { name: "Save decision", exact: true }).click(),
      ]);
      assert.equal(receiptResponse.status(), 200);
      const receipt = await receiptResponse.json();
      assert.equal(receipt.relationship_id, relation.relationship_id);
      assert.equal(receipt.decision, decision);
      assert.equal(receipt.decision_revision, relation.decision_revision + 1);
      await card.getByText("Decision saved by service", { exact: false }).waitFor();
      report.reviews.push({ ...receipt, corrected_entity_id: correctedEntityId });
    }
    await capture("05-confirm-correct-reject");
    report.relations_after = await read(`/versions/${relationFile.version_id}/relations`);
    for (const receipt of report.reviews) {
      const saved = report.relations_after.find((item) => item.relationship_id === receipt.relationship_id);
      assert.equal(saved.decision, receipt.decision);
      assert.equal(saved.decision_revision, receipt.decision_revision);
      assert.equal(saved.corrected_entity_id, receipt.corrected_entity_id);
    }
    await page.reload();
    await page.locator(".relation-card").first().waitFor();
    assert.deepEqual((await page.locator(".relation-state").allTextContents()).slice(0, 3), ["Confirmed", "Corrected", "Rejected"]);
    await capture("06-review-persists-after-reload");
  }
  assert.deepEqual(report.page_errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack || String(error);
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  report.finished_at = new Date().toISOString();
  report.git_head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
  report.source_sha256 = Object.fromEntries(["frontend/src/app.jsx", "frontend/src/relations-page.jsx", "frontend/src/api/http-adapter.js"].map((name) =>
    [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(repo, name))).digest("hex")]));
  fs.writeFileSync(path.join(output, "browser-live-report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
}
console.log(`W7 live browser workflow: ${report.cases.length} cases passed; no HTTP interception.`);
