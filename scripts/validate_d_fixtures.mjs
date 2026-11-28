import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(repoRoot, "fixtures");
const manifestPath = path.join(fixtureRoot, "manifest.json");
const mockDataPath = path.join(repoRoot, "frontend", "src", "mock", "data.json");

function assert(condition, message) {
  if (!condition) throw new Error(`Fixture validation failed: ${message}`);
}

function digest(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const mockData = JSON.parse(fs.readFileSync(mockDataPath, "utf8"));
assert(manifest.files.length === 16, "expected 16 files");
assert(manifest.pages_total === 20, "expected 20 normal PDF pages");
assert(manifest.categories.normal === 12, "expected 12 normal files");
assert(manifest.categories.abnormal === 3, "expected 3 abnormal files");
assert(manifest.categories.unsupported === 1, "expected 1 unsupported file");

const ids = new Set();
let normalCount = 0;
let abnormalCount = 0;
let unsupportedCount = 0;
let pageTotal = 0;
for (const file of manifest.files) {
  assert(!ids.has(file.file_id), `duplicate file id ${file.file_id}`);
  ids.add(file.file_id);
  const absolutePath = path.join(fixtureRoot, file.relative_path);
  assert(fs.existsSync(absolutePath), `missing ${file.relative_path}`);
  const bytes = fs.readFileSync(absolutePath);
  assert(digest(bytes) === file.sha256, `sha mismatch ${file.file_id}`);
  if (file.expected_status === "basic_ready") {
    normalCount += 1;
    pageTotal += file.page_count;
    assert(bytes.subarray(0, 8).toString("ascii") === "%PDF-1.4", `normal file is not PDF ${file.file_id}`);
    const pageMarkers = [...bytes.toString("ascii").matchAll(/\/Type \/Page\b/g)].length;
    assert(pageMarkers === file.page_count, `page count mismatch ${file.file_id}`);
  } else if (file.expected_status === "failed") {
    abnormalCount += 1;
    assert(Boolean(file.expected_error_code), `missing error code ${file.file_id}`);
  } else if (file.expected_status === "unsupported") {
    unsupportedCount += 1;
    assert(file.expected_error_code === "UNSUPPORTED_FORMAT", "unsupported error code mismatch");
  }
}

assert(normalCount === 12, "normal count mismatch");
assert(abnormalCount === 3, "abnormal count mismatch");
assert(unsupportedCount === 1, "unsupported count mismatch");
assert(pageTotal === 20, "page total mismatch");

const mockFilesById = new Map(mockData.files.map((file) => [file.file_id, file]));
assert(mockFilesById.size === manifest.files.length, "mock file inventory size mismatch");
let evidenceTotal = 0;
for (const file of manifest.files) {
  const mockFile = mockFilesById.get(file.file_id);
  assert(mockFile, `missing mock file ${file.file_id}`);
  assert(mockFile.version_id === file.version_id, `mock version mismatch ${file.file_id}`);
  assert(mockFile.relative_path === file.relative_path, `mock path mismatch ${file.file_id}`);
  assert(mockFile.page_count === file.page_count, `mock page count mismatch ${file.file_id}`);
  const evidence = mockData.evidence[`${file.file_id}:${file.version_id}`] || [];
  assert(evidence.length === file.page_count, `evidence count mismatch ${file.file_id}`);
  evidence.forEach((item, index) => {
    assert(item.file_id === file.file_id, `evidence file id mismatch ${file.file_id}`);
    assert(item.version_id === file.version_id, `evidence version mismatch ${file.file_id}`);
    assert(item.page === index + 1, `evidence page sequence mismatch ${file.file_id}`);
    assert(item.source_path === file.relative_path, `evidence source path mismatch ${file.file_id}`);
  });
  evidenceTotal += evidence.length;
}
assert(evidenceTotal === 20, "expected 20 traceable evidence pages");
console.log(`Fixture validation passed: ${manifest.files.length} files, ${pageTotal} normal PDF pages.`);
