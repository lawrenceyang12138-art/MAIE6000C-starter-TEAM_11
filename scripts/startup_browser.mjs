// Playwright resolves Chrome's installation for the current operating system.
// Each launch creates an isolated browser; it never attaches to a user session.
export async function launchStartupBrowser(chromium, {
  executablePath = process.env.STARTUP_BROWSER_EXECUTABLE,
} = {}) {
  const options = { headless: true, args: ["--disable-gpu"] };
  if (executablePath) {
    // An explicit override must fail visibly instead of selecting another browser.
    return chromium.launch({ ...options, executablePath });
  }

  try {
    return await chromium.launch({ ...options, channel: "chrome" });
  } catch (chromeError) {
    try {
      // Use Playwright's own installed Chromium when system Chrome is unavailable.
      return await chromium.launch(options);
    } catch (chromiumError) {
      throw new AggregateError([chromeError, chromiumError],
        "Unable to launch Chrome or Playwright Chromium. Install Chrome, run " +
        "`node frontend/node_modules/playwright-core/cli.js install chromium` " +
        "from the repository root, or set STARTUP_BROWSER_EXECUTABLE to an " +
        "installed Chromium executable.");
    }
  }
}
