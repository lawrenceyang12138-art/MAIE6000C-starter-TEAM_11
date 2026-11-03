// Isolated headless browser check against the real running stack, not fixtures.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, stat, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { launchStartupBrowser } from "./startup_browser.mjs";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { chromium } = require("../frontend/node_modules/playwright-core");
const origin = process.env.STARTUP_BROWSER_ORIGIN || "http://127.0.0.1:13000";
const retryMode = process.env.STARTUP_BROWSER_RETRY === "1";
const output = resolve(repo, retryMode ? "work/startup-browser-retry.json" : "work/startup-browser.json");
const evidence = { origin, mode: retryMode ? "error_explicit_retry_offline_recovery" : "observe_preparation", started_at: new Date().toISOString(), responses: [], page_errors: [], captures: [] };
const retryGate = process.env.STARTUP_BROWSER_RETRY_GATE ? resolve(repo, process.env.STARTUP_BROWSER_RETRY_GATE) : null;
if (retryMode) {
  assert.ok(retryGate, "Explicit gate file path is required before retrying the real service.");
  assert.ok(!relative(repo, retryGate).startsWith(".."), "Retry gate must be within this worktree.");
  await assert.rejects(stat(retryGate), { code: "ENOENT" }, "Retry gate must not already exist.");
}
const browser = await launchStartupBrowser(chromium);
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.on("pageerror", (error) => evidence.page_errors.push(error.message));
  page.on("response", async (response) => {
    if (new URL(response.url()).pathname !== "/api/setup") return;
    try {
      evidence.responses.push({ at: new Date().toISOString(), status: response.status(), body: await response.json() });
    } catch { /* non-JSON failures are observed by the UI and page assertions */ }
  });
  const initialRead = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/setup");
  await page.goto(origin + "/select");
  await initialRead;
  const panel = page.getByRole("region", { name: "Local AI preparation" });
  await panel.waitFor({ state: "visible" });
  if (retryMode) {
    console.log("Browser watcher active; waiting for a real preparation error.");
    await panel.getByRole("status").filter({ hasText: "Local AI preparation stopped" }).waitFor({ timeout: 600000 });
    const failedResponse = evidence.responses.at(-1);
    assert.equal(failedResponse.status, 200);
    assert.equal(failedResponse.body.state, "error");
    assert.equal(failedResponse.body.ready, false);
    assert.equal(failedResponse.body.retryable, true);
    const retryButton = panel.getByRole("button", { name: "Retry AI preparation" });
    assert.equal(await retryButton.isEnabled(), true);
    const failureScreenshot = resolve(repo, "work/startup-browser-error.png");
    await page.screenshot({ path: failureScreenshot, fullPage: true });
    evidence.captures.push({ stage: "error", at: new Date().toISOString(), panel: await panel.innerText(), screenshot: failureScreenshot });
    await mkdir(dirname(output), { recursive: true });
    await writeFile(output, JSON.stringify(evidence, null, 2) + "\n");
    console.log("Captured real error; waiting for explicit retry gate: " + retryGate);
    const gateDeadline = Date.now() + 600000;
    for (;;) {
      try { await stat(retryGate); break; }
      catch (error) { if (error.code !== "ENOENT") throw error; }
      assert.ok(Date.now() < gateDeadline, "Timed out waiting for the explicit retry gate.");
      await new Promise((done) => setTimeout(done, 1000));
    }
    const retryRead = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/setup/retry");
    await retryButton.click();
    const receipt = await retryRead;
    evidence.retry_receipt = { at: new Date().toISOString(), status: receipt.status(), body: await receipt.json() };
    assert.equal(receipt.status(), 202);
    console.log("Explicit UI retry accepted with HTTP 202.");
    await page.waitForFunction(() => {
      const title = document.querySelector(".setup-progress strong")?.textContent;
      return title && !["Local AI preparation stopped", "Retrying local AI preparation…"].includes(title);
    }, null, { timeout: 60000 });
    const retryScreenshot = resolve(repo, "work/startup-browser-retry.png");
    const retryStage = await panel.getAttribute("data-state") || await panel.getByRole("status").innerText();
    await page.screenshot({ path: retryScreenshot, fullPage: true });
    evidence.captures.push({ stage: retryStage, at: new Date().toISOString(), panel: await panel.innerText(), screenshot: retryScreenshot });
    await panel.getByRole("status").filter({ hasText: "Local AI is ready" }).waitFor({ timeout: 600000 });
    const lastRead = evidence.responses.at(-1);
    assert.equal(lastRead.status, 200);
    assert.equal(lastRead.body.state, "ready");
    assert.equal(lastRead.body.ready, true);
    assert.equal(await panel.getByRole("progressbar").count(), 0);
    const recoveryReads = evidence.responses.filter((read) => Date.parse(read.at) >= Date.parse(evidence.retry_receipt.at));
    evidence.observed_recovery_states = [...new Set(recoveryReads.map((read) => read.body.state))];
    assert.equal(recoveryReads.some((read) => read.body.state === "downloading"), false);
    const finalScreenshot = resolve(repo, "work/startup-browser-retry-ready.png");
    await page.screenshot({ path: finalScreenshot, fullPage: true });
    evidence.captures.push({ stage: "ready", at: new Date().toISOString(), panel: await panel.innerText(), screenshot: finalScreenshot });
    assert.equal(evidence.page_errors.length, 0);
    evidence.passed = true;
    console.log("Real UI error → explicit retry → ready checks passed.");
  } else {
  await page.waitForFunction(() => document.querySelector(".setup-progress strong")?.textContent !== "Preparing local AI");
  const initialResponse = evidence.responses.at(-1);
  assert.equal(initialResponse.status, 200);
  const initialState = initialResponse.body.state;
  assert.ok(["checking_environment", "installing_dependencies", "checking_model", "downloading", "verifying", "loading", "warming_up", "ready"].includes(initialState));
  const progress = await panel.getByRole("progressbar").count() ? await panel.getByRole("progressbar").evaluate((element) => ({
    value: element.getAttribute("value"), label: element.getAttribute("aria-label"), max: element.max,
  })) : null;
  const initialText = await panel.innerText();
  if (initialState !== "ready") {
    assert.equal(initialResponse.body.ready, false);
    assert.ok(progress);
    assert.equal(progress.max, 100);
    if (initialResponse.body.progress != null || initialResponse.body.stage_progress != null) {
      assert.notEqual(progress.value, null);
      assert.ok(Number(progress.value) >= 0 && Number(progress.value) <= 100);
      assert.equal(progress.label, initialResponse.body.progress == null
        ? "Current preparation stage progress" : "Local AI preparation progress");
    } else {
      assert.equal(progress.value, null);
    }
    assert.match(initialText, /Keyword search and original source evidence remain available/);
  }
  if (initialState === "downloading") {
    assert.match(initialText, /of this stage/);
    assert.match(initialText, /(?:KiB|MiB|GiB)/);
  }
  assert.equal(await page.getByRole("button", { name: "Authorize and start scan" }).isVisible(), true);
  const initialScreenshot = resolve(repo, "work/startup-browser-" + initialState + ".png");
  await page.screenshot({ path: initialScreenshot, fullPage: true });
  evidence.captures.push({ stage: initialState, at: new Date().toISOString(), panel: initialText, progress, screenshot: initialScreenshot });
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(evidence, null, 2) + "\n");
  console.log("Captured real " + initialState + " status: " + initialText.replaceAll("\n", " · "));

  await panel.getByRole("status").filter({ hasText: "Local AI is ready" }).waitFor({ timeout: 600000 });
  const readyResponse = evidence.responses.at(-1);
  assert.equal(readyResponse.status, 200);
  assert.equal(readyResponse.body.state, "ready");
  assert.equal(readyResponse.body.ready, true);
  assert.equal(await panel.getByRole("progressbar").count(), 0);
  assert.match(await panel.innerText(), /Model verified and warmed up/);
  const readyScreenshot = resolve(repo, "work/startup-browser-ready.png");
  await page.screenshot({ path: readyScreenshot, fullPage: true });
  evidence.captures.push({ stage: "ready", at: new Date().toISOString(), panel: await panel.innerText(), screenshot: readyScreenshot });
  assert.equal(evidence.page_errors.length, 0);
  evidence.passed = true;
  console.log("Captured real ready state; browser checks passed.");
  }
} catch (error) {
  evidence.passed = false;
  evidence.failure = error.message;
  throw error;
} finally {
  evidence.finished_at = new Date().toISOString();
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(evidence, null, 2) + "\n");
  await browser.close();
}
