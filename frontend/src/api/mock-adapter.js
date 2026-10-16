import { AdapterError } from "./errors.js";

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
  let lastCreatedJob = null;

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
    jobs.set(jobId, { jobId, rootId, sequence: sequenceFor(rootId) });
    jobCursors.set(jobId, 0);
    lastCreatedJob = jobId;
    return { status_code: 202, root_id: rootId, job_id: jobId, status: "pending" };
  }

  return {
    mode: "mock",
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
      if (lastCreatedJob && jobCursors.get(lastCreatedJob) < sequenceFor(jobs.get(lastCreatedJob).rootId).length - 1) {
        throw new AdapterError("An active scan already exists for this target.", { status: 409, code: "ACTIVE_JOB_EXISTS" });
      }
      const isEmpty = relativePath === "empty";
      const rootId = isEmpty ? "root-empty-01" : data.root.root_id;
      const jobId = isEmpty ? "job-scan-empty-01" : "job-scan-demo-01";
      return makeJob(jobId, rootId);
    },
    async getJob(jobId) {
      await delay(latency);
      if (!jobs.has(jobId)) {
        if (jobId === data.accepted_scan.job_id) {
          jobs.set(jobId, { jobId, rootId: data.root.root_id, sequence: data.progress_sequence });
          jobCursors.set(jobId, 0);
        } else {
          throw new AdapterError("Scan job not found.", { status: 404, code: "UNKNOWN_JOB" });
        }
      }
      const current = jobs.get(jobId);
      const cursor = jobCursors.get(jobId) ?? 0;
      const progress = clone(current.sequence[cursor]);
      if (cursor < current.sequence.length - 1) jobCursors.set(jobId, cursor + 1);
      return {
        ...progress,
        job_id: jobId,
        root_id: current.rootId,
        target: "scan_root",
        attempts: 1,
        error_code: progress.status === "failed" ? "SCAN_FAILED" : null,
      };
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
    async getEvidence(fileId, versionId) {
      await delay(latency);
      const evidence = data.evidence[`${fileId}:${versionId}`];
      const file = data.files.find((item) => item.file_id === fileId);
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
  };
}
