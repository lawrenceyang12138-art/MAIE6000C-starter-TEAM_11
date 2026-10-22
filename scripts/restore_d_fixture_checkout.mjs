// Restore checkout-only CRLF damage, preserving the original frozen hashes.
// All candidates are validated before writing; user content changes are refused.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const freeze = JSON.parse(fs.readFileSync(path.join(repo, "submissions/week07/gold-queries.freeze.json"), "utf8"));
const manifest = JSON.parse(fs.readFileSync(path.join(repo, "fixtures/manifest.json"), "utf8"));
const digest = (bytes) => crypto.createHash("sha256").update(bytes).digest("hex");
const targets = [
  { name: "fixtures/manifest.json", sha: freeze.manifest_sha256 },
  { name: "submissions/week07/gold-queries.json", sha: freeze.gold_sha256 },
  ...manifest.files.map((file) => ({ name: "fixtures/" + file.relative_path, sha: file.sha256 })),
];
const repairs = [];
for (const { name, sha } of targets) {
  const absolute = path.resolve(repo, name);
  assert.ok(absolute.startsWith(repo + path.sep), "Path must stay inside repository");
  const current = fs.readFileSync(absolute);
  if (digest(current) === sha) continue;
  const committed = execFileSync("git", ["show", "HEAD:" + name], { cwd: repo });
  assert.equal(digest(committed), sha, "HEAD does not match frozen bytes: " + name);
  const normalized = Buffer.from(current.toString("latin1").replace(/\r\n/g, "\n"), "latin1");
  assert.ok(normalized.equals(committed), "Refusing non-CRLF user changes: " + name);
  repairs.push({ absolute, committed });
}
for (const { absolute, committed } of repairs) fs.writeFileSync(absolute, committed);
console.log(`Restored ${repairs.length} checkout files to their original frozen bytes; no hashes changed.`);
