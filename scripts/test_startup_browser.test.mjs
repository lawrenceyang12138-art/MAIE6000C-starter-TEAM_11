import assert from "node:assert/strict";
import { test } from "node:test";
import { launchStartupBrowser } from "./startup_browser.mjs";

function launcher(outcomes) {
  const calls = [];
  return {
    calls,
    async launch(options) {
      calls.push(options);
      const result = outcomes[calls.length - 1];
      if (result instanceof Error) throw result;
      return result;
    },
  };
}

test("an executable override launches an isolated headless browser with that path", async () => {
  const browser = {};
  const chromium = launcher([browser]);
  const executablePath = "/custom/Chromium.app/Contents/MacOS/Chromium";
  assert.equal(await launchStartupBrowser(chromium, { executablePath }), browser);
  assert.deepEqual(chromium.calls, [{
    headless: true, args: ["--disable-gpu"], executablePath,
  }]);
});

test("STARTUP_BROWSER_EXECUTABLE overrides automatic discovery", async () => {
  const previous = process.env.STARTUP_BROWSER_EXECUTABLE;
  process.env.STARTUP_BROWSER_EXECUTABLE = "C:/Custom Chrome/chrome.exe";
  try {
    const chromium = launcher([{}]);
    await launchStartupBrowser(chromium);
    assert.equal(chromium.calls[0].executablePath, process.env.STARTUP_BROWSER_EXECUTABLE);
    assert.equal(chromium.calls[0].channel, undefined);
  } finally {
    if (previous === undefined) delete process.env.STARTUP_BROWSER_EXECUTABLE;
    else process.env.STARTUP_BROWSER_EXECUTABLE = previous;
  }
});

test("the default delegates Chrome discovery to Playwright on the current OS", async () => {
  const browser = {};
  const chromium = launcher([browser]);
  assert.equal(await launchStartupBrowser(chromium, { executablePath: "" }), browser);
  assert.deepEqual(chromium.calls, [{
    headless: true, args: ["--disable-gpu"], channel: "chrome",
  }]);
});

test("an installed Playwright Chromium works when system Chrome is unavailable", async () => {
  const browser = {};
  const chromium = launcher([new Error("Chrome is not installed"), browser]);
  assert.equal(await launchStartupBrowser(chromium, { executablePath: "" }), browser);
  assert.deepEqual(chromium.calls, [
    { headless: true, args: ["--disable-gpu"], channel: "chrome" },
    { headless: true, args: ["--disable-gpu"] },
  ]);
});

test("unavailable browsers report install/override guidance and both launch errors", async () => {
  const errors = [new Error("Chrome missing"), new Error("Chromium missing")];
  const chromium = launcher(errors);
  await assert.rejects(launchStartupBrowser(chromium, { executablePath: "" }), (error) => {
    assert.ok(error instanceof AggregateError);
    assert.deepEqual(error.errors, errors);
    assert.match(error.message, /playwright-core\/cli\.js install chromium/);
    assert.match(error.message, /STARTUP_BROWSER_EXECUTABLE/);
    return true;
  });
  assert.equal(chromium.calls.length, 2);
});

test("an invalid explicit executable fails without silently falling back", async () => {
  const failure = new Error("The requested executable does not exist");
  const chromium = launcher([failure, {}]);
  await assert.rejects(launchStartupBrowser(chromium, { executablePath: "/missing/chrome" }),
    (error) => error === failure);
  assert.equal(chromium.calls.length, 1);
});
