export const STATUS_META = {
  pending: { label: "Pending", tone: "pending" },
  running: { label: "Scanning", tone: "running" },
  completed: { label: "Scan complete", tone: "success" },
  failed: { label: "Scan failed", tone: "danger" },
  retry_wait: { label: "Retry scheduled", tone: "pending" },
  canceled: { label: "Canceled", tone: "warning" },
  discovered: { label: "Queued for extraction", tone: "pending" },
  extracting: { label: "Extracting", tone: "running" },
  basic_ready: { label: "Basic searchable", tone: "success" },
  enriched: { label: "AI enriched", tone: "success" },
  failed_file: { label: "Parse error", tone: "danger" },
  unsupported: { label: "Unsupported", tone: "warning" },
  stale: { label: "Source changed", tone: "warning" },
  missing: { label: "Source missing", tone: "danger" },
  unreadable: { label: "Source unreadable", tone: "danger" },
};

export function statusMeta(status) {
  return STATUS_META[status] || { label: status, tone: "neutral" };
}

export function summarizeProgress(root) {
  const counts = root?.file_counts;
  const fields = ["total", "basic_ready", "enriched", "failed", "unsupported"];
  const known = fields.every((key) => Number.isSafeInteger(counts?.[key]) && counts[key] >= 0);
  const normal = known ? counts.basic_ready + counts.enriched : null;
  const processed = known ? normal + counts.failed + counts.unsupported : null;
  const valid = known && processed <= counts.total;
  return {
    known: valid,
    total: valid ? counts.total : null,
    processed: valid ? processed : null,
    normal: valid ? normal : null,
    abnormal: valid ? counts.failed : null,
    unsupported: valid ? counts.unsupported : null,
    pending: valid ? counts.total - processed : null,
    percent: valid ? (counts.total === 0 ? 100 : Math.round(processed / counts.total * 100)) : null,
  };
}

export function shouldPoll(job, root) {
  if (["failed", "canceled"].includes(job?.status)) return false;
  const progress = summarizeProgress(root);
  return job?.status !== "completed" || !progress.known || progress.pending > 0;
}

export function dedupeFiles(files) {
  const seen = new Set();
  return files.filter((file) => {
    const key = `${file.file_id}:${file.version_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function isSourceUnavailable(file, error) {
  return file?.source_available === false ||
    ["stale", "missing", "unreadable"].includes(file?.status) ||
    ["SOURCE_UNAVAILABLE", "STALE_VERSION"].includes(error?.code);
}

export function isEvidenceForVersion(evidence, fileId, versionId, { sourcePath, pageCount } = {}) {
  if (pageCount !== undefined && (!Number.isSafeInteger(pageCount) || pageCount < 0)) return false;
  if (sourcePath !== undefined && typeof sourcePath !== "string") return false;
  return Array.isArray(evidence) && evidence.every(
    (item) => item?.file_id === fileId && item.version_id === versionId && Number.isInteger(item.page) && item.page > 0 &&
      (sourcePath === undefined || (typeof item.source_path === "string" && item.source_path.replaceAll("\\", "/") === sourcePath.replaceAll("\\", "/"))) &&
      (pageCount === undefined || item.page <= pageCount),
  );
}
