// Real Chromium against the local application. No HTTP interception, seeded
// browser state, or direct API writes. Only run on a fresh disposable stack.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values: options } = parseArgs({ options: {
  ui: { type: "string", default: "http://127.0.0.1:3000" },
  suite: { type: "string", default: "pdf" },
  manifest: { type: "string" },
  output: { type: "string" },
  "expect-sha": { type: "string" },
  "timeout-ms": { type: "string", default: "120000" },
  rescan: { type: "boolean", default: false },
  help: { type: "boolean", default: false },
} });
if (options.help) {
  console.log([
    "node scripts/verify_w13_browser.mjs --ui http://127.0.0.1:3000 --suite pdf --output work/w13/pdf-run",
    "node scripts/verify_w13_browser.mjs --ui http://127.0.0.1:3000 --suite mixed --manifest work/w13/mixed-fixture/browser-manifest.json --output work/w13/mixed-run",
    "",
    "Use an isolated, ready API-mode Compose stack with AI disabled and a fresh database.",
    "PDF: default corpus '.', both parser switches off (19 files, 7 rejected).",
    "Mixed: enable requested formats and mount the independent manifest's sources read-only.",
    "Optional: --expect-sha FULL_SHA (must match a clean tracked checkout), --rescan, --timeout-ms 120000.",
    "PDF checks require Python with pypdf; set D_PYTHON_EXECUTABLE to override 'python'.",
    "Set D_BROWSER_EXECUTABLE or D_PLAYWRIGHT_MODULE to reuse local Chrome and Playwright.",
    "Reports go in a new directory under work/. Image provenance and restart/DB checks are separate.",
  ].join("\n"));
  process.exit(0);
}

const repo = fs.realpathSync(fileURLToPath(new URL("../", import.meta.url)));
const base = new URL(options.ui);
assert.ok(base.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname),
  "--ui must be a loopback HTTP frontend origin.");
assert.ok(base.pathname === "/" && !(base.username || base.password || base.search || base.hash), "--ui takes only the frontend origin.");
assert.ok(["pdf", "mixed"].includes(options.suite), "--suite must be pdf or mixed.");
assert.equal(Boolean(options.manifest), options.suite === "mixed", "--manifest is required for mixed and not used for pdf.");
const timeout = Number(options["timeout-ms"]);
assert.ok(Number.isSafeInteger(timeout) && timeout >= 15000 && timeout <= 600000, "--timeout-ms must be 15000–600000.");
assert.ok(options.output, "Use --output with a new directory under work/.");
const output = path.resolve(repo, options.output);
const outputParts = path.relative(repo, output).split(path.sep);
assert.ok(outputParts[0] === "work" && outputParts.length >= 2, "--output must be below work/.");
let outputParent = repo;
for (const component of outputParts.slice(0, -1)) {
  outputParent = path.join(outputParent, component);
  try { fs.mkdirSync(outputParent); } catch (error) { if (error.code !== "EEXIST") throw error; }
  assert.ok(fs.lstatSync(outputParent).isDirectory(), "The output path must not cross symlinks or files.");
}
fs.mkdirSync(output); // Deliberately fails if the run directory already exists.

const git = (...args) => execFileSync("git", args, { cwd: repo, encoding: "utf8" }).trim();
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/u, ""));
const slash = (value) => value.replaceAll("\\", "/");
const relativeName = (file) => slash(path.relative(repo, file));
const safeRelative = (value) => typeof value === "string" && value.length > 0 &&
  !/[:\\\x00-\x1f]/u.test(value) && value.split("/").every((part) => part && part !== "." && part !== "..");
const isSha = (value) => typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
const fold = (value) => value.replace(/\s+/gu, " ").trim();
const formatFlags = { txt: "TEXT_PARSING_ENABLED", md: "TEXT_PARSING_ENABLED", docx: "DOCX_PARSING_ENABLED" };
const origin = (suffix) => new URL(suffix, base).href;
const report = {
  schema: "team11-w13-browser-v1", status: "running", started_at: new Date().toISOString(),
  evidence_type: "live_browser_api_worker", http_interception: false, mock_data: false,
  suite: options.suite, ui_origin: base.origin, rescan_requested: options.rescan,
  limitations: ["No automatic human sign-off", "Server image/SHA provenance must be recorded separately",
    "Not a same-volume restart or DB job-delta check", "Keyword-only; no semantic or hybrid claim"],
  checks: [], requests: [], page_errors: [],
};
const requestMatches = (suffix, method) => (response) => {
  const url = new URL(response.url());
  return url.origin === base.origin && url.pathname === "/api" + suffix && response.request().method() === method;
};
const local = (file) => {
  const real = fs.realpathSync(path.resolve(repo, file));
  assert.ok(safeRelative(relativeName(real)), "Fixture and manifest paths must resolve within the checkout.");
  assert.ok(fs.statSync(real).isFile(), "Fixture or manifest is not a file.");
  return real;
};

function pdfSuite() {
  const frozen = local("fixtures/search/w13-v1/manifest.json");
  const gold = local("fixtures/search/w13-v1/queries.json");
  report.manifests = [frozen, gold].map((file) => ({ path: relativeName(file), sha256: sha(fs.readFileSync(file)) }));
  const sources = readJson(frozen).files.filter(({ group }) => group === "w7-compose").map((item) => ({
    ...item, path: item.relative_path, status: item.status === "ready" ? "basic_ready" : item.status,
  }));
  for (const extension of ["txt", "md", "docx"]) {
    const name = "note." + extension;
    const fixture = "tests/fixtures/formats/" + name;
    const bytes = fs.readFileSync(local(fixture));
    sources.push({ path: "formats/" + name, fixture_path: fixture, status: "unsupported",
      error_code: "unsupported_format", sha256: sha(bytes), byte_size: bytes.length });
  }
  assert.equal(sources.length, 19);
  assert.equal(sources.filter(({ status }) => status === "unsupported").length, 7);
  const queries = ["K01", "K02"].map((id) => {
    const row = readJson(gold).queries.find((entry) => entry.id === id);
    const { path: wantedPath, page, quote } = row.expected[0];
    return { path: wantedPath, page, text: quote, exact_text: false, query: row.query, lang: "en" };
  });
  return { mount_id: "corpus", relative_path: ".", sources, queries,
    expected_flags: { TEXT_PARSING_ENABLED: false, DOCX_PARSING_ENABLED: false } };
}

function mixedSuite() {
  const manifestFile = local(options.manifest);
  report.manifests = [{ path: relativeName(manifestFile), sha256: sha(fs.readFileSync(manifestFile)) }];
  const manifest = readJson(manifestFile);
  assert.ok(typeof manifest.mount_id === "string" && manifest.mount_id, "Mixed mount_id is required.");
  assert.ok(manifest.relative_path === "." || safeRelative(manifest.relative_path), "Mixed relative_path is invalid.");
  assert.ok(Array.isArray(manifest.sources) && manifest.sources.length > 0, "Mixed sources are required.");
  assert.ok(manifest.queries === undefined || Array.isArray(manifest.queries), "Mixed queries must be an array.");
  const sources = manifest.sources.map((entry) => {
    assert.ok(safeRelative(entry.path), "Mixed source path is invalid.");
    assert.ok(["pdf", "txt", "md", "docx"].includes(entry.format) && entry.path.toLowerCase().endsWith("." + entry.format),
      "Mixed source format must agree with its path.");
    return { ...entry, fixture_path: entry.fixture_path || path.join(path.dirname(manifestFile), "sources", entry.path) };
  });
  const expectedFlags = Object.fromEntries([...new Set(Object.values(formatFlags))]
    .filter((key) => typeof manifest.expected_flags?.[key] === "boolean")
    .map((key) => [key, manifest.expected_flags[key]]));
  for (const format of new Set(sources.map(({ format }) => format))) {
    const entries = sources.filter((source) => source.format === format);
    if (expectedFlags[formatFlags[format]] === false) {
      assert.ok(entries.every(({ status, error_code }) => status === "unsupported" && error_code === "unsupported_format"),
        "A disabled format must explicitly expect rejection for all of its fixtures: " + format);
      continue;
    }
    for (const lang of ["en", "zh"]) {
      assert.ok(entries.some((source) => source.status === "basic_ready" && source.query && source.lang === lang),
        "Mixed suite needs an independent ready " + lang + " query for " + format + ".");
    }
    assert.ok(entries.some((source) => ["failed", "unsupported"].includes(source.status) && source.error_code),
      "Mixed suite needs a rejected source for " + format + ".");
  }
  assert.ok(sources.some(({ format }) => format === "pdf") && sources.some(({ format }) => format !== "pdf"),
    "Mixed suite must regress PDF with at least one intended non-PDF format.");
  return { ...manifest, expected_flags: expectedFlags, sources, queries: [
    ...sources.filter(({ status }) => status === "basic_ready"),
    ...(manifest.queries || []),
  ] };
}

function readPhysicalPage(file, page) {
  const code = "import sys; from pypdf import PdfReader; text = PdfReader(sys.argv[1]).pages[int(sys.argv[2]) - 1].extract_text(); sys.stdout.buffer.write(text.encode('utf-8'))";
  return execFileSync(process.env.D_PYTHON_EXECUTABLE || "python", ["-B", "-c", code, file, String(page)],
    { cwd: repo, encoding: "utf8", timeout: 30000 });
}

function snapshotSources(sources, checkFrozen) {
  return sources.map((entry) => {
    assert.ok(safeRelative(entry.path) && isSha(entry.sha256), "Invalid fixture path or SHA-256: " + entry.path);
    assert.ok(["basic_ready", "failed", "unsupported"].includes(entry.status), "Unknown source status: " + entry.path);
    if (entry.status !== "basic_ready") assert.match(entry.error_code || "", /^[a-z][a-z0-9_]{1,63}$/u);
    const bytes = fs.readFileSync(local(entry.fixture_path));
    const digest = sha(bytes);
    if (checkFrozen) {
      assert.equal(digest, entry.sha256, "Frozen SHA-256 mismatch: " + entry.path);
      if (entry.byte_size !== undefined) assert.equal(bytes.length, entry.byte_size, "Frozen byte size mismatch: " + entry.path);
    }
    return { path: entry.path, sha256: digest, byte_size: bytes.length };
  });
}

let browser, page;
let checkpoint = "preflight";
const read = async (suffix) => {
  const response = await page.request.get(origin("/api" + suffix), { maxRedirects: 0 });
  assert.equal(response.status(), 200, "GET /api" + suffix);
  return response.json();
};
async function screenshot(name) {
  await page.locator(".mode-api").waitFor();
  assert.equal(await page.locator(".mode-mock").count(), 0, "Browser must not be in mock mode.");
  assert.equal(new URL(page.url()).origin, base.origin, "Browser left the chosen local origin.");
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true });
  report.checks.push({ name, screenshot: name + ".png", status: "passed" });
}
async function settled(accepted) {
  const deadline = Date.now() + timeout;
  const { job_id: jobId, root_id: rootId } = accepted;
  while (Date.now() < deadline) {
    const job = await read("/jobs/" + encodeURIComponent(jobId));
    assert.equal(job.root_id, rootId);
    assert.ok(!["failed", "canceled"].includes(job.status), "Scan job did not complete: " + (job.error_code || job.status));
    const root = await read("/roots/" + encodeURIComponent(rootId));
    const counts = root.file_counts;
    if (job.status === "completed" && counts?.total > 0 &&
        counts.basic_ready + counts.enriched + counts.failed + counts.unsupported === counts.total) {
      return { job, root, files: await read("/files?root_id=" + encodeURIComponent(rootId)) };
    }
    await sleep(450);
  }
  throw new Error("The real Worker did not settle within " + timeout + " ms.");
}
function rowFor(sourcePath) {
  return page.locator(".file-row").filter({ has: page.getByText(sourcePath, { exact: true }) });
}
async function keywordSearch(query) {
  await page.getByLabel("Search query", { exact: true }).fill(query);
  const [response] = await Promise.all([
    page.waitForResponse(requestMatches("/search", "POST")),
    page.getByRole("button", { name: "Search", exact: true }).click(),
  ]);
  assert.equal(response.status(), 200);
  const request = response.request().postDataJSON();
  assert.equal(request.root_id, report.accepted.root_id);
  const search = await response.json();
  assert.equal(search.mode, "keyword");
  assert.equal(search.effective_mode, "keyword");
  assert.equal(search.degraded, false);
  return search;
}

try {
  report.git_head = git("rev-parse", "HEAD");
  report.tracked_git_status = git("status", "--porcelain", "--untracked-files=no");
  if (options["expect-sha"] !== undefined) {
    assert.match(options["expect-sha"], /^[a-f0-9]{40}$/u, "--expect-sha takes a full commit SHA.");
    assert.equal(report.git_head, options["expect-sha"], "Checkout does not match the requested candidate.");
    assert.equal(report.tracked_git_status, "", "Tracked changes prevent a same-SHA claim.");
  }
  report.verifier_sha256 = sha(fs.readFileSync(fileURLToPath(import.meta.url)));
  report.frontend_source_sha256 = Object.fromEntries(
    ["app.jsx", "api/http-adapter.js", "lib/search.js", "styles.css"].map((file) =>
      [file, sha(fs.readFileSync(path.join(repo, "frontend", "src", file)))]));

  const suite = options.suite === "pdf" ? pdfSuite() : mixedSuite();
  const sources = new Map(suite.sources.map((entry) => [entry.path, entry]));
  assert.equal(sources.size, suite.sources.length, "Manifest must specify each source once.");
  report.scope = { mount_id: suite.mount_id, relative_path: suite.relative_path,
    expected_flags: suite.expected_flags, expected_search_mode: "keyword", expected_ai_setup_state: "disabled",
    expected_sources: suite.sources.map(({ path, status, error_code }) => ({ path, status, error_code })) };
  report.fixture_bytes_before = snapshotSources(suite.sources, true);
  const oracle = suite.queries.map((query) => {
    const source = sources.get(query.path);
    assert.ok(source?.status === "basic_ready" && typeof query.query === "string" && query.query.trim() &&
      typeof query.text === "string" && query.text.trim(), "Invalid query or expected passage for " + query.path);
    const pdf = source.path.toLowerCase().endsWith(".pdf");
    assert.ok(pdf ? Number.isSafeInteger(query.page) && query.page > 0 : query.page === null, "Expected locator is invalid: " + query.path);
    assert.ok(pdf || query.exact_text !== false, "Native format must specify the exact independent passage: " + query.path);
    assert.ok((options.suite === "pdf" && query.ordinal === undefined) ||
      (Number.isSafeInteger(query.ordinal) && query.ordinal > 0), "Expected ordinal is invalid: " + query.path);
    const physicalText = pdf ? fold(readPhysicalPage(local(source.fixture_path), query.page)) : null;
    if (pdf) assert.ok(physicalText.includes(fold(query.text)), "Gold quote not on the original PDF page: " + query.path);
    return { ...query, source, physicalText };
  });

  checkpoint = "browser startup and API readiness";
  const require = createRequire(path.join(repo, "frontend/package.json"));
  const { chromium } = require(process.env.D_PLAYWRIGHT_MODULE || "playwright-core");
  browser = await chromium.launch({ headless: true, ...(process.env.D_BROWSER_EXECUTABLE
    ? { executablePath: process.env.D_BROWSER_EXECUTABLE } : { channel: "chrome" }) });
  report.browser = browser.version();
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  page.setDefaultTimeout(20000);
  page.on("pageerror", (error) => report.page_errors.push(error.message));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === base.origin && url.pathname.startsWith("/api/")) {
      report.requests.push({ path: url.pathname, method: response.request().method(), status: response.status() });
    }
  });
  report.ready = await read("/health/ready");
  report.setup = await read("/setup");
  assert.equal(report.setup.state, "disabled", "Configure EMBEDDING_ENABLED=false for this keyword-only acceptance run.");
  const mounts = await read("/mounts");
  assert.equal(mounts.find((item) => item.mount_id === suite.mount_id)?.read_only, true, "Expected read-only mount is not configured.");

  checkpoint = "authorize and scan";
  await page.goto(origin("/select"));
  await page.locator(".mode-api").waitFor();
  assert.equal(await page.locator(".mode-mock").count(), 0);
  await page.getByText("Example/configured directories", { exact: true }).click();
  await page.getByLabel("Read-only mount", { exact: true }).selectOption(suite.mount_id);
  await page.getByLabel("Configured directory", { exact: true }).selectOption(suite.relative_path);
  const [scanResponse] = await Promise.all([
    page.waitForResponse(requestMatches("/roots", "POST")),
    page.getByRole("button", { name: "Authorize and start scan" }).click(),
  ]);
  assert.equal(scanResponse.status(), 202);
  assert.deepEqual(scanResponse.request().postDataJSON(), { mount_id: suite.mount_id, relative_path: suite.relative_path });
  report.accepted = await scanResponse.json();
  assert.equal(report.accepted.status, "pending");
  assert.ok(report.accepted.job_id && report.accepted.root_id);
  await page.waitForURL(origin("/scan/" + report.accepted.job_id));
  report.imported = await settled(report.accepted);
  await page.reload();
  await page.getByRole("progressbar", { name: "File processing progress" }).waitFor();
  await page.locator(".page-heading .status-badge").filter({ hasText: "Scan complete" }).waitFor();
  await screenshot("01-import-progress");
  await page.getByRole("button", { name: "View available files and evidence" }).click();

  checkpoint = "catalog and negative cases";
  const files = new Map(report.imported.files.map((file) => [file.relative_path, file]));
  assert.equal(report.imported.files.length, sources.size, "Unexpected exact catalog size.");
  assert.equal(files.size, sources.size, "Duplicate file path in catalog.");
  for (const status of ["basic_ready", "enriched", "unsupported", "failed"]) {
    assert.equal(report.imported.root.file_counts[status], suite.sources.filter((entry) => entry.status === status).length,
      "Unexpected root count: " + status);
  }
  for (const [index, entry] of suite.sources.entries()) {
    const file = files.get(entry.path);
    assert.equal(file?.status, entry.status, "Unexpected terminal state: " + entry.path);
    assert.equal(file?.root_id, report.accepted.root_id);
    assert.ok(typeof file.file_id === "string" && typeof file.version_id === "string");
    if (entry.status === "basic_ready") {
      assert.equal(file.error_code, null);
    } else {
      assert.equal(file.error_code, entry.error_code, "Incorrect API rejection: " + entry.path);
      const reason = rowFor(entry.path).locator(".file-warning");
      await reason.waitFor();
      assert.equal(await reason.textContent(), entry.error_code, "Incorrect UI rejection: " + entry.path);
      await reason.scrollIntoViewIfNeeded();
      await screenshot("02-rejection-" + (index + 1));
    }
  }

  report.evidence = [];
  for (const [index, query] of oracle.entries()) {
    checkpoint = "search and source: " + query.path + " (" + query.query + ")";
    const search = await keywordSearch(query.query);
    const result = { expected_path: query.path, expected_page: query.page, expected_ordinal: query.ordinal ?? null,
      expected_sha256: query.source.sha256, query: query.query, search };
    report.evidence.push(result);
    const hit = search.results.find((item) => item.file_path === query.path);
    assert.ok(hit, "Expected file absent from the actual search results: " + query.path);
    assert.equal(hit.root_id, report.accepted.root_id);
    assert.equal(hit.file_id, files.get(query.path).file_id);
    assert.equal(hit.version_id, files.get(query.path).version_id);
    assert.equal(hit.page, query.page);
    assert.ok(typeof hit.chunk_id === "string" && hit.chunk_id.length > 0);
    assert.ok(Number.isSafeInteger(hit.ordinal) && hit.ordinal > 0);
    if (query.ordinal !== undefined) assert.equal(hit.ordinal, query.ordinal);
    const locator = query.page === null ? "原文片段 #" + hit.ordinal : "Page " + query.page;
    const row = rowFor(query.path);
    await row.locator(".passage-locator").waitFor();
    assert.equal(await row.locator(".passage-locator").textContent(), locator);
    const [sourceResponse] = await Promise.all([
      page.waitForResponse(requestMatches("/evidence/" + encodeURIComponent(hit.chunk_id), "GET")),
      row.getByRole("button").click(),
    ]);
    assert.equal(sourceResponse.status(), 200);
    const evidence = await sourceResponse.json();
    result.source = evidence;
    assert.equal(evidence.chunk_id, hit.chunk_id);
    assert.equal(evidence.version_id, hit.version_id);
    assert.equal(evidence.file_id, hit.file_id);
    assert.equal(evidence.relative_path, query.path);
    assert.equal(evidence.ordinal, hit.ordinal);
    assert.equal(evidence.page_number, query.page);
    assert.equal(evidence.content_sha256, query.source.sha256);
    assert.ok(hit.text && evidence.text.startsWith(hit.text), "Search excerpt is not a prefix of the verified original.");
    if (query.exact_text === false) assert.ok(fold(evidence.text).includes(fold(query.text)), "The reviewed source quote is missing.");
    else assert.equal(evidence.text, query.text, "The full original native passage differs from the independent manifest.");
    if (query.physicalText !== null) assert.ok(query.physicalText.includes(fold(evidence.text)), "Passage differs from the independently read physical PDF page.");
    const inspector = page.locator(".inspector-pane");
    const record = inspector.locator(".evidence-record");
    await record.waitFor();
    assert.equal(await inspector.locator(".evidence-locator").textContent(), locator);
    assert.equal(await inspector.locator(".evidence-detail-heading code").textContent(), evidence.version_id);
    assert.equal(await record.locator(".page-index").textContent(), locator);
    assert.equal(await record.locator("strong").textContent(), query.path);
    assert.equal(await record.locator("p").textContent(), evidence.text);
    assert.equal(await record.locator(".evidence-hash").textContent(), "SHA-256 " + evidence.content_sha256);
    result.ui_locator = locator;
    result.independent_comparison = query.physicalText === null ? "manifest text and source SHA-256" : "physical PDF page, frozen quote and source SHA-256";
    await screenshot("03-source-" + (index + 1));
  }
  assert.ok(!report.requests.some(({ path }) => /^\/api\/files\/[^/]+\/evidence$/u.test(path)), "Legacy file/page evidence endpoint was requested.");
  if (typeof suite.absent_keyword === "string" && suite.absent_keyword.trim()) {
    checkpoint = "absent keyword";
    report.absent_keyword = await keywordSearch(suite.absent_keyword);
    assert.equal(report.absent_keyword.total, 0);
    assert.deepEqual(report.absent_keyword.results, []);
    await page.getByRole("heading", { name: "No matches found" }).waitFor();
    await screenshot("04-no-matches");
  }

  if (options.rescan) {
    checkpoint = "rescan preserves identities";
    const scope = "/roots/" + encodeURIComponent(report.accepted.root_id) + "/scans";
    const [rescanResponse] = await Promise.all([
      page.waitForResponse(requestMatches(scope, "POST")),
      page.getByRole("button", { name: "Rescan directory", exact: true }).click(),
    ]);
    assert.equal(rescanResponse.status(), 202);
    const acceptance = await rescanResponse.json();
    assert.equal(acceptance.root_id, report.accepted.root_id);
    assert.notEqual(acceptance.job_id, report.accepted.job_id);
    assert.equal(acceptance.status, "pending");
    report.rescan = { accepted: acceptance, ...await settled(acceptance) };
    const identities = (rows) => rows.map(({ file_id, version_id, relative_path, status, error_code }) =>
      [relative_path, file_id, version_id, status, error_code]).sort(([a], [b]) => a.localeCompare(b));
    assert.deepEqual(identities(report.rescan.files), identities(report.imported.files));
    for (const { source } of report.evidence) {
      assert.deepEqual(await read("/evidence/" + encodeURIComponent(source.chunk_id)), source, "Rescan changed an inspected chunk.");
    }
    await page.waitForURL(origin("/scan/" + acceptance.job_id));
    await page.locator(".page-heading .status-badge").filter({ hasText: "Scan complete" }).waitFor();
    await screenshot("05-rescan");
  }

  checkpoint = "source read-only check";
  report.fixture_bytes_after = snapshotSources(suite.sources, false);
  assert.deepEqual(report.fixture_bytes_after, report.fixture_bytes_before, "A source fixture changed during the run.");
  assert.equal(git("rev-parse", "HEAD"), report.git_head, "Checkout changed during the run.");
  assert.equal(git("status", "--porcelain", "--untracked-files=no"), report.tracked_git_status, "Tracked worktree changed during the run.");
  assert.deepEqual(report.page_errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.failure = { checkpoint, message: error.message };
  if (page) await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true, timeout: 5000 }).catch(() => {});
  console.error("W13 browser check failed at " + checkpoint + ": " + error.message);
  process.exitCode = 1;
} finally {
  report.finished_at = new Date().toISOString();
  fs.writeFileSync(path.join(output, "browser-live-report.json"), JSON.stringify(report, null, 2) + "\n");
  if (browser) await browser.close();
}

console.log("W13 " + report.suite + " browser check " + report.status + ": " + path.join(output, "browser-live-report.json"));
