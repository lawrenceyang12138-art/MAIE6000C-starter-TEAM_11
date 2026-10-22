import { POLL_MAX_ATTEMPTS, POLL_MAX_MS, dedupeFiles, isEvidenceForVersion, nextPollDelay, shouldPoll, statusMeta, summarizeProgress } from "./scan.js";

describe("scan presentation helpers", () => {
  it("uses independent current-file counts rather than scan-job percentages", () => {
    expect(summarizeProgress({ file_counts: { total: 16, basic_ready: 12, enriched: 0, failed: 3, unsupported: 1 } })).toEqual({
      known: true,
      total: 16,
      processed: 16,
      normal: 12,
      abnormal: 3,
      unsupported: 1,
      pending: 0,
      percent: 100,
    });
    expect(summarizeProgress({ total: 10, processed: 12, percent: 140 })).toMatchObject({ known: false, percent: null });
    expect(summarizeProgress({ file_counts: { total: 0, basic_ready: 0, enriched: 0, failed: 0, unsupported: 0 } })).toMatchObject({ known: true, percent: 100 });
  });

  it("deduplicates repeated scans by file and version", () => {
    const files = [
      { file_id: "file-001", version_id: "v1" },
      { file_id: "file-001", version_id: "v1", scan_note: "duplicate" },
      { file_id: "file-001", version_id: "v2" },
    ];
    expect(dedupeFiles(files)).toHaveLength(2);
    expect(dedupeFiles(files)[0].scan_note).toBeUndefined();
  });

  it("accepts only evidence tied to the visible version", () => {
    expect(isEvidenceForVersion([{ file_id: "f1", version_id: "v1", page: 2 }], "f1", "v1")).toBe(true);
    expect(isEvidenceForVersion([{ file_id: "f1", version_id: "v2", page: 2 }], "f1", "v1")).toBe(false);
    expect(isEvidenceForVersion([{ file_id: "f1", version_id: "v1", page: 0 }], "f1", "v1")).toBe(false);
  });

  it("maps file and job statuses to visible tones", () => {
    expect(statusMeta("completed")).toMatchObject({ label: "Scan complete", tone: "success" });
    expect(statusMeta("unsupported")).toMatchObject({ label: "Unsupported", tone: "warning" });
    expect(statusMeta("something-new").tone).toBe("neutral");
  });

  it("pauses progress polling at the attempt budget", () => {
    const done = { status: "completed" };
    const complete = { file_counts: { total: 0, basic_ready: 0, enriched: 0, failed: 0, unsupported: 0 } };
    expect(shouldPoll(done, complete)).toBe(false);
    expect(shouldPoll(done, undefined)).toBe(true);
    expect(shouldPoll(done, undefined, { pollCount: POLL_MAX_ATTEMPTS - 1 })).toBe(true);
    expect(shouldPoll(done, undefined, { pollCount: POLL_MAX_ATTEMPTS })).toBe(false);
    expect(shouldPoll({ status: "failed" }, undefined)).toBe(false);
  });

  it("backs off the polling delay and caps it", () => {
    expect(nextPollDelay(0)).toBe(900);
    expect(nextPollDelay(1)).toBe(1350);
    expect(nextPollDelay(2)).toBe(2025);
    expect(nextPollDelay(50)).toBe(POLL_MAX_MS);
  });
});
