import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(repoRoot, "fixtures");
const mockRoot = path.join(repoRoot, "frontend", "src", "mock");

const ROOT_ID = "root-demo-01";
const GENERATED_AT = "2026-10-14T09:00:00Z";

function ensureDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true });
}

function escapePdfText(value) {
  return value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
}

function createPdf(title, pageCount) {
  const objects = [null, null];
  const addObject = (body) => {
    objects.push(body);
    return objects.length;
  };

  const pageIds = [];
  const contentIds = [];
  const fontId = addObject("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

  for (let page = 1; page <= pageCount; page += 1) {
    const text = escapePdfText(`${title} | synthetic page ${page} of ${pageCount}`);
    const content = `BT /F1 14 Tf 72 720 Td (${text}) Tj 0 -28 Td (Team 11 demo fixture) Tj ET`;
    const contentId = addObject(`<< /Length ${Buffer.byteLength(content, "ascii")} >>\nstream\n${content}\nendstream`);
    const pageId = addObject(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${fontId} 0 R >> >> /Contents ${contentId} 0 R >>`,
    );
    contentIds.push(contentId);
    pageIds.push(pageId);
  }

  const pagesId = 2;
  const catalogId = 1;
  const pages = pageIds.map((id) => `${id} 0 R`).join(" ");
  objects[catalogId - 1] = `<< /Type /Catalog /Pages ${pagesId} 0 R >>`;
  objects[pagesId - 1] = `<< /Type /Pages /Kids [${pages}] /Count ${pageCount} >>`;

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((body, index) => {
    const objectNumber = index + 1;
    offsets.push(Buffer.byteLength(pdf, "ascii"));
    pdf += `${objectNumber} 0 obj\n${body}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf, "ascii");
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index < offsets.length; index += 1) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf, "ascii");
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

// The HTTP contract validates a per-chunk digest (`GET /evidence/{chunk_id}`).
// Never reuse the file hash for it: the chunk hash must identify this passage,
// so the mock fixture and the real service agree on what is being verified.
function chunkDigest(fileId, versionId, page, excerpt) {
  return sha256(Buffer.from([fileId, versionId, page, excerpt].join("|"), "utf8"));
}

function writeFile(relativePath, contents) {
  const absolutePath = path.join(fixtureRoot, relativePath);
  ensureDirectory(path.dirname(absolutePath));
  fs.writeFileSync(absolutePath, contents);
  return absolutePath;
}

function normalRecord(index, directory, pageCount) {
  const fileId = `file-${String(index).padStart(3, "0")}`;
  const versionId = `version-${String(index).padStart(3, "0")}-v1`;
  const fileName = `team11-demo-${String(index).padStart(2, "0")}.pdf`;
  const relativePath = `normal/${directory}/${fileName}`;
  const bytes = createPdf(`Team 11 synthetic document ${String(index).padStart(2, "0")}`, pageCount);
  writeFile(relativePath, bytes);
  return {
    file_id: fileId,
    version_id: versionId,
    relative_path: relativePath,
    display_name: fileName,
    sha256: sha256(bytes),
    page_count: pageCount,
    expected_status: "basic_ready",
    expected_error_code: null,
    source_kind: "synthetic_pdf",
    root_id: ROOT_ID,
  };
}

function abnormalRecord(index, fileName, bytes, errorCode) {
  const fileId = `file-${String(index).padStart(3, "0")}`;
  const versionId = `version-${String(index).padStart(3, "0")}-v1`;
  const relativePath = `abnormal/${fileName}`;
  writeFile(relativePath, bytes);
  return {
    file_id: fileId,
    version_id: versionId,
    relative_path: relativePath,
    display_name: fileName,
    sha256: sha256(bytes),
    page_count: 0,
    expected_status: "failed",
    expected_error_code: errorCode,
    source_kind: "synthetic_invalid_pdf",
    root_id: ROOT_ID,
  };
}

function unsupportedRecord(index) {
  const fileId = `file-${String(index).padStart(3, "0")}`;
  const versionId = `version-${String(index).padStart(3, "0")}-v1`;
  const fileName = "team11-unsupported-notes.docx";
  const relativePath = `unsupported/${fileName}`;
  const bytes = Buffer.from("Team 11 synthetic unsupported-format placeholder\n", "utf8");
  writeFile(relativePath, bytes);
  return {
    file_id: fileId,
    version_id: versionId,
    relative_path: relativePath,
    display_name: fileName,
    sha256: sha256(bytes),
    page_count: 0,
    expected_status: "unsupported",
    expected_error_code: "UNSUPPORTED_FORMAT",
    source_kind: "synthetic_unsupported",
    root_id: ROOT_ID,
  };
}

function buildManifest() {
  const files = [];
  for (let index = 1; index <= 12; index += 1) {
    const directory = index <= 6 ? "team-alpha" : "team-beta";
    const pageCount = index <= 8 ? 1 : 3;
    files.push(normalRecord(index, directory, pageCount));
  }
  files.push(
    abnormalRecord(13, "empty.pdf", Buffer.alloc(0), "EMPTY_FILE"),
    abnormalRecord(14, "truncated.pdf", Buffer.from("%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\n", "ascii"), "TRUNCATED_PDF"),
    abnormalRecord(15, "corrupt.pdf", Buffer.from("not a PDF document\n", "utf8"), "CORRUPT_PDF"),
    unsupportedRecord(16),
  );

  const manifest = {
    manifest_version: "d-fixtures-v1",
    generated_at: GENERATED_AT,
    root_id: ROOT_ID,
    root_label: "Team 11 synthetic demo mount",
    pages_total: files.reduce((total, file) => total + file.page_count, 0),
    categories: { normal: 12, abnormal: 3, unsupported: 1 },
    files,
  };
  writeFile("manifest.json", JSON.stringify(manifest, null, 2) + "\n");
  return manifest;
}

function buildMockData(manifest) {
  ensureDirectory(mockRoot);
  const files = manifest.files.map((file) => ({
    ...file,
    status: file.expected_status,
    source_available: file.file_id !== "file-004",
    capability_status: file.file_id === "file-005" ? "keyword_only" : "full",
    snippet:
      file.expected_status === "basic_ready"
        ? `Synthetic evidence for ${file.display_name}`
        : `Processing stopped: ${file.expected_error_code}`,
    evidence_count: file.page_count,
  }));

  const evidence = {};
  files
    .filter((file) => file.page_count > 0)
    .forEach((file) => {
      evidence[`${file.file_id}:${file.version_id}`] = Array.from(
        { length: file.page_count },
        (_, pageIndex) => {
          const excerpt = `${file.display_name} page ${pageIndex + 1} synthetic excerpt`;
          return {
            evidence_id: `evidence-${file.file_id}-${pageIndex + 1}`,
            file_id: file.file_id,
            version_id: file.version_id,
            page: pageIndex + 1,
            source_path: file.relative_path,
            excerpt,
            content_sha256: chunkDigest(file.file_id, file.version_id, pageIndex + 1, excerpt),
          };
        },
      );
    });

  const mockData = {
    contract_version: "d-mock-contract-v1",
    generated_at: GENERATED_AT,
    root: {
      root_id: ROOT_ID,
      mount_id: "mount-team11-demo",
      label: manifest.root_label,
      relative_path: "normal",
      status: "active",
    },
    mounts: [
      {
        mount_id: "mount-team11-demo",
        label: "Team 11 synthetic demo mount",
        read_only: true,
        availability: "available",
      },
    ],
    directories: {
      "mount-team11-demo": [
        { relative_path: "normal", label: "normal", kind: "directory" },
        { relative_path: "normal/team-alpha", label: "team-alpha", kind: "directory" },
        { relative_path: "normal/team-beta", label: "team-beta", kind: "directory" },
        { relative_path: "abnormal", label: "abnormal", kind: "directory" },
        { relative_path: "unsupported", label: "unsupported", kind: "directory" },
        { relative_path: "empty", label: "empty (no files)", kind: "directory" },
      ],
    },
    accepted_scan: {
      status_code: 202,
      root_id: ROOT_ID,
      job_id: "job-scan-demo-01",
      status: "pending",
    },
    progress_sequence: [
      { status: "pending", processed: 0, total: 16, normal: 0, abnormal: 0, unsupported: 0, percent: 0 },
      { status: "running", processed: 6, total: 16, normal: 6, abnormal: 0, unsupported: 0, percent: 38 },
      { status: "running", processed: 12, total: 16, normal: 12, abnormal: 0, unsupported: 0, percent: 75 },
      { status: "completed", processed: 16, total: 16, normal: 12, abnormal: 3, unsupported: 1, percent: 100 },
    ],
    files,
    evidence,
  };
  ensureDirectory(mockRoot);
  fs.writeFileSync(path.join(mockRoot, "data.json"), JSON.stringify(mockData, null, 2) + "\n");
}

const manifest = buildManifest();
buildMockData(manifest);
console.log(`Generated ${manifest.files.length} fixtures and ${manifest.pages_total} normal pages.`);
