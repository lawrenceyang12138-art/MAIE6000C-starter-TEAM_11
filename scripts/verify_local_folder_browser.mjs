// Isolated browser HTTP consumer-contract fixtures. No native chooser or Docker acceptance.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { launchStartupBrowser } from "./startup_browser.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "frontend/package.json"));
const { chromium } = require("playwright-core");
const baseUrl = (process.env.D_UI_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const helperUrl = (process.env.D_LOCAL_FOLDER_BRIDGE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
for (const value of [baseUrl, helperUrl]) assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(new URL(value).hostname), "Contract fixtures require loopback origins.");
const output = path.resolve(repo, process.env.D_UI_OUTPUT || "work/local-folders-browser");
fs.mkdirSync(output, { recursive: true });
const disclaimer = "HTTP CONTRACT FIXTURE — NO NATIVE CHOOSER OR DOCKER ACCEPTANCE";
const report = { kind: "browser_http_contract_fixture", disclaimer, ui: baseUrl, helper: helperUrl,
  started_at: new Date().toISOString(), cases: [], requests: [], page_errors: [], console_errors: [], request_failures: [], screenshots: [], passed: false };
const browser = await launchStartupBrowser(chromium, { executablePath: process.env.D_BROWSER_EXECUTABLE || process.env.STARTUP_BROWSER_EXECUTABLE });
const storageKey = "filetrace.localFolderOperation";
const folderName = "个人项目资料 (contract fixture)";
const displayPath = "D:\\个人项目资料 (contract fixture)\\Research and project documents\\A long folder name to verify narrow viewport wrapping";
const rootId = "root-folder-contract";
const jobId = 42;
const mountedId = "local-contract-source";
const zeroCounts = { total: 0, discovered: 0, extracting: 0, basic_ready: 0, enriched: 0, failed: 0, unsupported: 0 };
const rootRecord = { root_id: rootId, mount_id: mountedId, relative_path: ".", status: "active", availability: "available", file_counts: zeroCounts };
let currentCase = "startup";

function record(name, details = {}) { report.cases.push({ name, status: "passed", ...details }); }

async function fixturePage(scenario) {
  currentCase = scenario;
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(30000);
  const fixture = { scenario, selectionPosts: 0, preparePosts: 0, rootPosts: 0, rootReads: 0,
    operation: null, progressReads: 0, states: [], rootExists: false, timeouts: [] };
  const rootFixture = () => ({ ...rootRecord });
  page.on("pageerror", (error) => report.page_errors.push({ scenario, message: error.message }));
  page.on("console", (message) => { if (message.type() === "error") report.console_errors.push({ scenario, message: message.text() }); });
  page.on("requestfailed", (request) => report.request_failures.push({ scenario, method: request.method(), url: request.url(), error: request.failure()?.errorText }));
  async function fulfill(route, body, status = 200, extraHeaders = {}) {
    await route.fulfill({ status, contentType: "application/json", headers: { "Cache-Control": "no-store", ...extraHeaders }, body: JSON.stringify(body) });
  }
  await context.route(helperUrl + "/**", async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname;
    const headers = { "Access-Control-Allow-Origin": new URL(baseUrl).origin,
      "Access-Control-Allow-Headers": "Content-Type, X-FileTrace-Session", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
    if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
    report.requests.push({ scenario, service: "helper_fixture", method: request.method(), endpoint });
    if (endpoint === "/status") {
      await fulfill(route, { available: true, protocol: 1, project_id: "folder-browser-contract", session_token: "synthetic-contract-session" }, 200, headers); return;
    }
    assert.equal(request.headers()["x-filetrace-session"], "synthetic-contract-session");
    if (endpoint === "/folder-selections" && request.method() === "POST") {
      fixture.selectionPosts += 1;
      const body = request.postDataJSON();
      assert.deepEqual(Object.keys(body), ["operation_id"]);
      assert.match(body.operation_id, /^[0-9a-f-]{36}$/i);
      fixture.operation = { operation_id: body.operation_id, state: scenario === "cancelled" ? "cancelled" : "selected",
        ...(scenario === "cancelled" ? {} : { folder_name: folderName, display_path: displayPath }) };
      await fulfill(route, fixture.operation, 202, headers); return;
    }
    const match = endpoint.match(/^\/folder-selections\/([0-9a-f-]+)(\/prepare)?$/i);
    if (match && fixture.operation?.operation_id === match[1]) {
      if (match[2] && request.method() === "POST") {
        fixture.preparePosts += 1;
        assert.deepEqual(request.postDataJSON(), {});
        fixture.operation = { ...fixture.operation, state: "waiting" };
        fixture.progressReads = 0;
        await fulfill(route, fixture.operation, 202, headers); return;
      }
      if (!match[2] && request.method() === "GET") {
        if (["waiting", "preparing", "reconnecting"].includes(fixture.operation.state)) {
          const stages = ["waiting", "preparing", "reconnecting", "ready"];
          fixture.operation = { ...fixture.operation, state: stages[Math.min(fixture.progressReads++, stages.length - 1)] };
          if (fixture.operation.state === "ready") fixture.operation.mount_id = mountedId;
        }
        fixture.states.push(fixture.operation.state);
        await fulfill(route, fixture.operation, 200, headers); return;
      }
    }
    await fulfill(route, { code: "not_found" }, 404, headers);
  });
  await context.route(new URL("/api/**", baseUrl).href, async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.replace(/^\/api/, "");
    report.requests.push({ scenario, service: "api_fixture", method: request.method(), endpoint });
    if (endpoint === "/setup") {
      await fulfill(route, { state: "disabled", ready: false, progress: null, stage_progress: null,
        downloaded_bytes: 0, total_bytes: null, completed_files: 0, total_files: 0, model: "synthetic-contract-model",
        message: "HTTP fixture only", retryable: false, updated_at: new Date().toISOString() }); return;
    }
    if (endpoint === "/mounts") { await fulfill(route, [{ mount_id: "configured-fixture", label: "Configured contract fixture", read_only: true }]); return; }
    if (endpoint === "/mounts/configured-fixture/directories") { await fulfill(route, [{ relative_path: ".", label: "Fixture root" }]); return; }
    if (endpoint === "/roots" && request.method() === "POST") {
      fixture.rootPosts += 1; fixture.rootExists = true;
      assert.deepEqual(request.postDataJSON(), { mount_id: mountedId, relative_path: "." });
      if (scenario === "scan-timeout") {
        // Keep the response pending past the consumer's 15s deadline; never reach a real API.
        await new Promise((resolve) => { const timer = setTimeout(resolve, 18000); fixture.timeouts.push(timer); });
        try { await fulfill(route, { root_id: rootId, job_id: jobId, status: "pending" }, 202); } catch { /* The consumer already aborted its timed-out read. */ }
        return;
      }
      await fulfill(route, { root_id: rootId, job_id: jobId, status: "pending" }, 202); return;
    }
    if (endpoint === "/roots" && request.method() === "GET") { fixture.rootReads += 1; await fulfill(route, fixture.rootExists ? [rootFixture()] : []); return; }
    if (endpoint === `/roots/${rootId}`) { await fulfill(route, rootFixture()); return; }
    if (endpoint === `/jobs/${jobId}`) { await fulfill(route, { root_id: rootId, job_id: jobId, status: "completed", attempts: 1, error_code: null }); return; }
    if (endpoint === "/files") { await fulfill(route, []); return; }
    await fulfill(route, { detail: { code: "contract_fixture_route_missing" } }, 404);
  });
  await page.goto(baseUrl + "/select", { waitUntil: "domcontentloaded" });
  await page.locator(".mode-api").waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll("button")].some((item) => item.textContent === "Choose local folder" && !item.disabled));
  return { context, page, fixture };
}

async function capture(page, name) {
  // Let responsive grid/inspector transitions finish after changing viewport size.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("body *")].map((element) => ({ tag: element.tagName, className: String(element.className), rect: element.getBoundingClientRect().toJSON() }))
      .filter((element) => element.rect.right > innerWidth + 1 || element.rect.left < -1).slice(0, 12) }));
  await page.evaluate((watermark) => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    document.getElementById("folder-contract-watermark")?.remove();
    const mark = document.createElement("div"); mark.id = "folder-contract-watermark"; mark.textContent = watermark;
    Object.assign(mark.style, { position: "fixed", top: "0", left: "0", zIndex: "99999", maxWidth: "100vw",
      padding: "4px 8px", background: "#7f1d1d", color: "white", font: "bold 11px/1.4 sans-serif", pointerEvents: "none", boxSizing: "border-box" });
    document.body.append(mark);
  }, disclaimer);
  const filename = name + ".png";
  await page.screenshot({ path: path.join(output, filename), fullPage: true });
  report.screenshots.push(filename);
  assert.ok(layout.scrollWidth <= layout.width, "Horizontal overflow: " + name + " " + JSON.stringify(layout));
}

async function choose(page) {
  await page.getByRole("button", { name: "Choose local folder", exact: true }).click();
  await page.locator(".local-folder-selection").waitFor();
}

try {
  {
    const { context, page, fixture } = await fixturePage("selected-before-consent");
    await choose(page);
    assert.equal(fixture.selectionPosts, 1); assert.equal(fixture.preparePosts, 0); assert.equal(fixture.rootPosts, 0);
    assert.equal(await page.locator(".local-folder-selection code").textContent(), displayPath);
    for (const width of [375, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await capture(page, `selected-${width}`);
      record(`Selected folder fits ${width}px without horizontal overflow`, { width });
    }
    assert.equal(fixture.preparePosts, 0); assert.equal(fixture.rootPosts, 0);
    record("Selection does not prepare or scan before explicit authorization");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(".local-folder-selection").waitFor();
    assert.equal(fixture.selectionPosts, 1); assert.equal(fixture.preparePosts, 0); assert.equal(fixture.rootPosts, 0);
    record("Refreshing a selected folder restores the same operation using reads");
    await context.close();
  }
  {
    const { context, page, fixture } = await fixturePage("cancelled");
    await page.getByRole("button", { name: "Choose local folder", exact: true }).click();
    await page.getByText("Folder selection cancelled. No folder was authorized.", { exact: true }).waitFor();
    assert.equal(fixture.selectionPosts, 1); assert.equal(fixture.preparePosts, 0); assert.equal(fixture.rootPosts, 0);
    await capture(page, "cancelled"); record("Cancelling selection grants no access and queues no scan");
    await context.close();
  }
  for (const scenario of ["authorized", "refresh-preparation"]) {
    const { context, page, fixture } = await fixturePage(scenario);
    await choose(page);
    await page.getByRole("button", { name: "Authorize and start scan", exact: true }).click();
    await page.getByText("Waiting for the current file task to finish before adding this folder…", { exact: true }).waitFor();
    assert.equal(fixture.rootPosts, 0);
    await capture(page, scenario + "-waiting");
    if (scenario === "refresh-preparation") await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForURL(`**/scan/${jobId}`, { timeout: 20000 });
    await page.getByText("Scan complete", { exact: true }).first().waitFor();
    assert.equal(fixture.selectionPosts, 1); assert.equal(fixture.preparePosts, 1); assert.equal(fixture.rootPosts, 1);
    for (const state of ["waiting", "preparing", "reconnecting", "ready"]) assert.ok(fixture.states.includes(state), `Missing preparation state ${state}`);
    await capture(page, scenario + "-scan");
    record(scenario === "authorized" ? "Preparation waits and reconnects before exactly one first scan" : "Refreshing preparation does not repeat selection, prepare, or first scan writes", { states: fixture.states, selection_posts: fixture.selectionPosts, prepare_posts: fixture.preparePosts, scan_posts: fixture.rootPosts });
    await context.close();
  }
  {
    const { context, page, fixture } = await fixturePage("scan-timeout");
    await choose(page);
    await page.getByRole("button", { name: "Authorize and start scan", exact: true }).click();
    await page.getByRole("button", { name: "View current indexed content", exact: true }).waitFor({ timeout: 30000 });
    assert.equal(fixture.rootPosts, 1); assert.ok(fixture.rootReads > 0);
    await page.getByText("Folder authorization exists. Scan acceptance is unconfirmed.", { exact: true }).waitFor();
    await capture(page, "scan-timeout-recovered-authorization");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "View current indexed content", exact: true }).waitFor();
    assert.equal(fixture.selectionPosts, 1); assert.equal(fixture.preparePosts, 1); assert.equal(fixture.rootPosts, 1);
    await page.getByRole("button", { name: "View current indexed content", exact: true }).click();
    await page.waitForURL(`**/results/${rootId}`);
    await page.getByText("No indexed files yet", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Authorize local directory", exact: true }).count(), 0);
    assert.equal(await page.evaluate((key) => sessionStorage.getItem(key), storageKey), null);
    await capture(page, "scan-timeout-results-safe-empty-state");
    record("A timed-out first scan recovers its authorization by reads without replay, including reload", { selection_posts: fixture.selectionPosts, prepare_posts: fixture.preparePosts, scan_posts: fixture.rootPosts, root_reads: fixture.rootReads });
    for (const timer of fixture.timeouts) clearTimeout(timer);
    await context.close();
  }
  assert.deepEqual(report.page_errors, [], "Browser runtime errors must be zero.");
  const unexpectedConsoleErrors = report.console_errors.filter((error) => !(error.scenario === "scan-timeout" && /Failed to load resource.*(?:ERR_ABORTED|ERR_FAILED|ERR_TIMED_OUT)/.test(error.message)));
  assert.deepEqual(unexpectedConsoleErrors, [], "Unexpected browser console errors.");
  report.passed = true;
  record("No page runtime errors or unexpected console errors");
} catch (error) {
  report.failure = { scenario: currentCase, message: error.message, stack: error.stack };
  throw error;
} finally {
  report.completed_at = new Date().toISOString();
  fs.writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
  process.stdout.write(JSON.stringify({ passed: report.passed, cases: report.cases.length, page_errors: report.page_errors.length, console_errors: report.console_errors.length, report: path.join(output, "report.json"), disclaimer }, null, 2) + "\n");
}
