// Explicit synthetic UI demonstration, without HTTP interception or product acceptance.
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
const baseUrl = process.env.D_UI_URL || "http://127.0.0.1:5190";
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseUrl).hostname));
const output = process.env.D_UI_OUTPUT ? path.resolve(repo, process.env.D_UI_OUTPUT) : path.join(repo, "submissions/week07/evidence/1019-D");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.D_BROWSER_EXECUTABLE ? { executablePath: process.env.D_BROWSER_EXECUTABLE } : { channel: "chrome" }) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
page.setDefaultTimeout(10000);
page.setDefaultNavigationTimeout(30000);
const cases = [], errors = [], apiRequests = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => { if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url()); });
let passed = false;
async function capture(name) {
  assert.equal(await page.locator(".mode-mock").count(), 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.evaluate(() => {
    document.querySelector("#sample-watermark")?.remove();
    const mark = document.createElement("div"); mark.id = "sample-watermark";
    mark.textContent = "SYNTHETIC MOCK SAMPLE - NOT PRODUCT ACCEPTANCE";
    Object.assign(mark.style, { position: "absolute", zIndex: 99999, top: "0", left: "0", maxWidth: "95vw", padding: "4px 8px", background: "#7f1d1d", color: "white", font: "bold 11px sans-serif", pointerEvents: "none" });
    document.body.append(mark);
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true });
  cases.push({ name, status: "passed" });
}
try {
  await page.goto(baseUrl + "/select", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Configured directory", { exact: true }).selectOption("sample");
  await page.getByRole("button", { name: "Authorize and start scan" }).click();
  await page.waitForURL("**/scan/job-scan-demo-01");
  assert.equal(await page.evaluate(() => sessionStorage.getItem("lastRootId")), "root-relations-demo");
  await capture("mock-relation-authorized");
  // Client navigation retains the same in-memory adapter instance.
  await page.getByRole("button", { name: "View available files and evidence" }).click();
  await page.getByLabel("Search query", { exact: true }).fill("Database Reliability");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.locator(".file-row-main").waitFor();
  await page.locator(".file-row-main").click();
  await page.locator(".inspector-pane .evidence-record").waitFor();
  await capture("mock-relation-search-evidence");
  await page.getByRole("button", { name: "Relations", exact: true }).click();
  await page.locator(".relation-card").first().waitFor();
  assert.equal(await page.locator(".relation-card").count(), 3);
  await capture("mock-relation-candidates");
  await page.getByRole("button", { name: "Human Review", exact: true }).click();
  for (const [label, decision] of [["Chen", "confirmed"], ["Atlas Project", "corrected"], ["Database Reliability", "rejected"]]) {
    const card = page.locator(".relation-card").filter({ has: page.getByRole("heading", { name: label, exact: true }) });
    assert.equal(await card.getByRole("button", { name: "Save decision", exact: true }).isDisabled(), true);
    await card.getByRole("button", { name: "Open source passage", exact: true }).click();
    await card.getByText("Source verified", { exact: false }).waitFor();
    await card.getByLabel("Reviewer", { exact: true }).fill("synthetic-reviewer");
    await card.getByLabel("Decision for " + label, { exact: true }).selectOption(decision);
    if (decision === "corrected") await card.getByLabel("Replacement entity for " + label, { exact: true }).selectOption("entity-chen");
    await card.getByRole("button", { name: "Save decision", exact: true }).click();
    await card.getByText("Decision saved by service", { exact: false }).waitFor();
    assert.equal(await card.locator(".relation-state").innerText(), { confirmed: "Confirmed", corrected: "Corrected", rejected: "Rejected" }[decision]);
  }
  await capture("mock-relation-decisions");
  await page.getByRole("button", { name: "Relations", exact: true }).click();
  await page.locator(".relation-card").first().waitFor();
  assert.deepEqual(await page.locator(".relation-state").allTextContents(), ["Confirmed", "Corrected", "Rejected"]);
  await page.setViewportSize({ width: 375, height: 1000 });
  await capture("mock-relation-mobile");
  assert.deepEqual(errors, []);
  assert.deepEqual(apiRequests, []);
  passed = true;
} finally {
  fs.writeFileSync(path.join(output, "browser-mock-relations-report.json"), JSON.stringify({
    status: passed ? "passed" : "failed", observed_at: new Date().toISOString(),
    evidence_type: "explicit_synthetic_mock_not_product", product_acceptance: false,
    http_interception: false, api_requests: apiRequests, page_errors: errors,
    git_head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim(),
    source_sha256: Object.fromEntries(["frontend/src/api/adapter.js", "frontend/src/api/mock-adapter.js", "frontend/src/mock/relations.json", "frontend/src/app.jsx", "frontend/src/relations-page.jsx"].map((name) =>
      [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(repo, name))).digest("hex")])),
    browser: browser.version(), cases,
  }, null, 2) + "\n");
  await browser.close();
}
console.log(`D relation Mock UI checks: ${cases.length} passed; product acceptance: false.`);
