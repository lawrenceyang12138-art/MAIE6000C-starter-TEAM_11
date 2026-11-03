import { AdapterError } from "./errors.js";
import { isSourceUnavailable } from "../lib/scan.js";
import { normalizeQuery } from "../lib/search.js";

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function pathIsAllowed(relativePath) {
  return (
    typeof relativePath === "string" &&
    relativePath.length > 0 &&
    !relativePath.split(/[\\/]/).includes("..") &&
    !relativePath.startsWith("/") &&
    !/^[a-zA-Z]:[\\/]/.test(relativePath) &&
    !relativePath.startsWith("\\\\")
  );
}

export function createMockAdapter(data, { latency = 80 } = {}) {
  const jobCursors = new Map();
  const jobs = new Map();
  const relations = clone(data.relations || {});
  const activeJobStatuses = new Set(["pending", "running", "retry_wait"]);
  let rescanCount = 0;

  function sequenceFor(rootId) {
    if (rootId === "root-empty-01") {
      return [
        { status: "pending", processed: 0, total: 0, normal: 0, abnormal: 0, unsupported: 0, percent: 0 },
        { status: "completed", processed: 0, total: 0, normal: 0, abnormal: 0, unsupported: 0, percent: 100 },
      ];
    }
    return data.progress_sequence;
  }

  function makeJob(jobId, rootId) {
    jobs.set(jobId, { jobId, rootId, sequence: sequenceFor(rootId), status: "pending", attempts: 1 });
    jobCursors.set(jobId, 0);
    return { status_code: 202, root_id: rootId, job_id: jobId, status: "pending" };
  }

  function hasActiveJob(rootId) {
    return [...jobs.values()].some((job) => job.rootId === rootId && activeJobStatuses.has(job.status));
  }

  return {
    mode: "mock",
    async getSetup() {
      return {
        state: "ready", ready: true, progress: 100, stage_progress: 100,
        downloaded_bytes: 0, total_bytes: null, completed_files: 0, total_files: 0,
        model: "simulated-local-model", message: "Simulated preparation only; no model was downloaded or loaded.",
        error_code: null, retryable: false, updated_at: new Date().toISOString(), simulated: true,
      };
    },
    async retrySetup() {
      return this.getSetup();
    },
    async listMounts() {
      await delay(latency);
      return clone(data.mounts);
    },
    async listDirectories(mountId) {
      await delay(latency);
      if (!data.directories[mountId]) {
        throw new AdapterError("Mount point not found.", { status: 404, code: "UNKNOWN_MOUNT" });
      }
      return clone(data.directories[mountId]);
    },
    async createRootScan(mountId, relativePath) {
      await delay(latency);
      if (!data.directories[mountId]) {
        throw new AdapterError("Mount point not found.", { status: 404, code: "UNKNOWN_MOUNT" });
      }
      if (!pathIsAllowed(relativePath)) {
        throw new AdapterError("Choose a relative directory inside a configured mount.", { status: 403, code: "PATH_OUT_OF_SCOPE" });
      }
      if (!data.directories[mountId].some((directory) => directory.relative_path === relativePath)) {
        throw new AdapterError("This relative directory is not allowed by the mount.", { status: 403, code: "PATH_OUT_OF_SCOPE" });
      }
      const isEmpty = relativePath === "empty";
      const rootId = isEmpty ? "root-empty-01" : data.root.root_id;
      if (hasActiveJob(rootId)) {
        throw new AdapterError("An active scan already exists for this target.", { status: 409, code: "ACTIVE_JOB_EXISTS" });
      }
      const jobId = isEmpty ? "job-scan-empty-01" : "job-scan-demo-01";
      return makeJob(jobId, rootId);
    },
    async getJob(jobId) {
      await delay(latency);
      if (!jobs.has(jobId)) {
        if (jobId === data.accepted_scan.job_id) {
          jobs.set(jobId, { jobId, rootId: data.root.root_id, sequence: data.progress_sequence, status: "pending", attempts: 1 });
          jobCursors.set(jobId, 0);
        } else {
          throw new AdapterError("Scan job not found.", { status: 404, code: "UNKNOWN_JOB" });
        }
      }
      const current = jobs.get(jobId);
      const cursor = jobCursors.get(jobId) ?? 0;
      const progress = clone(current.sequence[cursor]);
      current.status = progress.status;
      if (cursor < current.sequence.length - 1) jobCursors.set(jobId, cursor + 1);
      return {
        ...progress,
        job_id: jobId,
        root_id: current.rootId,
        target: "scan_root",
        attempts: current.attempts,
        error_code: progress.status === "failed" ? "SCAN_FAILED" : null,
      };
    },
    async retryJob(jobId, rootId) {
      await delay(latency);
      const current = jobs.get(jobId);
      if (!current || current.rootId !== rootId) {
        throw new AdapterError("Scan job not found.", { status: 404, code: "UNKNOWN_JOB" });
      }
      if (current.status !== "failed") {
        throw new AdapterError("Only a failed scan job can be retried.", { status: 409, code: "JOB_NOT_RETRYABLE" });
      }
      const lastProgress = current.sequence.at(-1);
      current.sequence = [
        { ...lastProgress, status: "pending" },
        { ...lastProgress, status: "completed" },
      ];
      current.status = "pending";
      current.attempts += 1;
      jobCursors.set(jobId, 0);
      return { status_code: 202, job_id: jobId, root_id: rootId, status: "pending" };
    },
    async rescanRoot(rootId) {
      await delay(latency);
      if (![data.root.root_id, "root-empty-01"].includes(rootId)) {
        throw new AdapterError("Directory authorization not found.", { status: 404, code: "unknown_root" });
      }
      if (hasActiveJob(rootId)) throw new AdapterError("A scan is already active for this directory.", { status: 409, code: "active_job_exists" });
      return makeJob(`job-rescan-demo-${++rescanCount}`, rootId);
    },
    async listFiles(rootId) {
      await delay(latency);
      if (rootId === "root-empty-01") return [];
      if (rootId !== data.root.root_id) {
        throw new AdapterError("Directory authorization not found.", { status: 404, code: "UNKNOWN_ROOT" });
      }
      const files = data.files.map((file) => ({
        ...clone(file),
        scan_note:
          file.file_id === "file-002"
            ? "Duplicate scan: reused the existing version"
            : file.file_id === "file-003"
              ? "Rollback protection: kept the current evidence"
              : file.status === "failed"
                ? "Needs attention before retry"
                : file.status === "unsupported"
                  ? "Waiting for format support"
                  : "First scan result",
      }));
      return clone(files);
    },
    async getRoot(rootId) {
      await delay(latency);
      if (rootId !== data.root.root_id && rootId !== "root-empty-01") {
        throw new AdapterError("Directory authorization not found.", { status: 404, code: "UNKNOWN_ROOT" });
      }
      const current = [...jobs.values()].findLast((job) => job.rootId === rootId);
      const sequence = sequenceFor(rootId);
      const cursor = current ? Math.max(0, (jobCursors.get(current.jobId) ?? 1) - 1) : sequence.length - 1;
      const progress = sequence[cursor];
      // Only an explicit mock adapter creates these demonstration aggregates.
      return {
        root_id: rootId, status: "active", availability: "available",
        file_counts: { total: progress.total, basic_ready: progress.normal, enriched: 0, failed: progress.abnormal, unsupported: progress.unsupported },
      };
    },
    async getEvidence(fileId, versionId) {
      await delay(latency);
      const evidence = data.evidence[`${fileId}:${versionId}`];
      const file = data.files.find((item) => item.file_id === fileId);
      if (file && file.version_id !== versionId) {
        throw new AdapterError("The file version changed. Reload the results.", { status: 409, code: "STALE_VERSION" });
      }
      if (file?.source_available === false) {
        throw new AdapterError("The source file is unavailable. Re-check the mounted directory.", { status: 404, code: "SOURCE_UNAVAILABLE" });
      }
      if (!evidence) {
        if (!file) throw new AdapterError("File not found.", { status: 404, code: "UNKNOWN_FILE" });
        if (file.version_id !== versionId) {
          throw new AdapterError("The file version changed. Reload the results.", { status: 409, code: "STALE_VERSION" });
        }
        throw new AdapterError("This file has no expandable evidence.", { status: 422, code: "NO_EVIDENCE" });
      }
      return clone(evidence);
    },
    async search({ query, rootId, fileId = null, mode = "hybrid", topK = 10 }) {
      await delay(latency);
      const normalized = normalizeQuery(query);
      if (!normalized || normalized.length > 500 || !["keyword", "hybrid", "semantic"].includes(mode) ||
        !Number.isInteger(topK) || topK < 1 || topK > 50) {
        throw new AdapterError("Enter a valid query and search mode.", { status: 422, code: "invalid_query" });
      }
      if (![data.root.root_id, "root-empty-01"].includes(rootId)) {
        throw new AdapterError("Directory authorization not found.", { status: 404, code: "unknown_root" });
      }
      // A deterministic keyword simulation only; never manufacture semantic scores.
      const needle = normalized.toLowerCase();
      const hits = rootId === "root-empty-01" ? [] : data.files.filter((file) =>
        ["basic_ready", "enriched"].includes(file.status) && !isSourceUnavailable(file) &&
        (!fileId || file.file_id === fileId)).flatMap((file) => {
        const passages = data.evidence[`${file.file_id}:${file.version_id}`] || [];
        const passage = passages.find((item) => `${file.display_name} ${file.relative_path} ${item.excerpt}`.toLowerCase().includes(needle));
        return passage ? [{ root_id: rootId, file_id: file.file_id, file_name: file.display_name,
          file_path: file.relative_path, version_id: file.version_id, version_created_at: file.updated_at || null,
          chunk_id: passage.evidence_id, ordinal: passages.indexOf(passage) + 1, page: passage.page,
          text: passage.excerpt, reason: "Synthetic keyword match", score: 1, keyword_score: 1, semantic_score: 0 }] : [];
      });
      return { query: normalized, mode, effective_mode: "keyword", results: clone(hits.slice(0, topK)),
        total: hits.length, degraded: mode !== "keyword", degradation_reason: mode !== "keyword" ? "mock_keyword_only" : null };
    },
    async getEvidenceByChunk(chunkId) {
      const passages = Object.values(data.evidence).flat();
      const passage = passages.find((item) => item.evidence_id === chunkId);
      if (!passage) throw new AdapterError("Passage not found.", { status: 404, code: "chunk_not_found" });
      // Reuse version/source checks instead of serving an old cached passage.
      const current = await this.getEvidence(passage.file_id, passage.version_id);
      // The HTTP contract binds evidence to a per-chunk digest. Never fall back
      // to the file digest: that would label a passage with the wrong hash.
      if (!/^[a-f0-9]{64}$/.test(passage.content_sha256 || "")) {
        throw new AdapterError("This synthetic passage has no chunk digest. Regenerate the mock fixtures.", { status: 500, code: "CONTRACT_MISMATCH" });
      }
      return { chunk_id: chunkId, file_id: passage.file_id, version_id: passage.version_id,
        relative_path: passage.source_path, page_number: passage.page, ordinal: current.findIndex((item) => item.evidence_id === chunkId) + 1,
        text: passage.excerpt, content_sha256: passage.content_sha256 };
    },
    async listRelations(versionId) {
      await delay(latency);
      if (!data.files.some((file) => file.version_id === versionId)) {
        throw new AdapterError("Version not found.", { status: 404, code: "no_current_version" });
      }
      // The frozen 16-file fixture has no relation candidates. The separate,
      // explicitly selected contract sample exercises this UI without altering it.
      return clone(relations[versionId] || []);
    },
    async recordReview(relationshipId, { decision, expectedRevision, correctedEntityId = null }) {
      await delay(latency);
      const relation = Object.values(relations).flat().find((item) => item.relationship_id === relationshipId);
      if (!relation) throw new AdapterError("No candidate exists in this synthetic sample.", { status: 404, code: "relationship_not_found" });
      if (!["confirmed", "corrected", "rejected"].includes(decision)) throw new AdapterError("Invalid decision.", { status: 422, code: "invalid_decision" });
      if (decision === "corrected" && !data.entities?.includes(correctedEntityId)) throw new AdapterError("Use an existing sample entity ID, such as entity-replacement.", { status: 422, code: "corrected_entity_not_found" });
      if (decision !== "corrected" && correctedEntityId != null) throw new AdapterError("Only a correction can name a replacement.", { status: 422, code: "correction_target_not_allowed" });
      if (relation.decision_revision !== expectedRevision) throw new AdapterError("Another simulated decision exists. Reload the latest revision.", { status: 409, code: "review_conflict" });
      relation.decision = decision;
      relation.corrected_entity_id = correctedEntityId;
      relation.decision_revision += 1;
      return { relationship_id: relationshipId, decision, decision_revision: relation.decision_revision };
    },
  };
}
