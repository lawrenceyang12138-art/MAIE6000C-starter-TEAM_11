import { describe, expect, it, vi } from "vitest";
import { createApiAdapter } from "./http-adapter.js";
import { createMockAdapter } from "./mock-adapter.js";

const setup = {
  state: "downloading", ready: false, progress: 20, stage_progress: 25,
  downloaded_bytes: 100, total_bytes: 400, completed_files: 1, total_files: 14,
  model: "perplexity-ai/pplx-embed-v2-late-0.6b@pinned", message: "Downloading",
  error_code: null, retryable: false, updated_at: "2026-10-30T00:00:00Z",
};
const response = (payload, status = 200) => ({ ok: true, status, json: async () => payload });

describe("preparation status adapter", () => {
  it("reads status and sends one explicit retry POST without changing search mode", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(response(setup)).mockResolvedValueOnce(response(setup, 202));
    const adapter = createApiAdapter({ fetchImpl });
    expect(await adapter.getSetup()).toEqual(setup);
    expect(await adapter.retrySetup()).toEqual(setup);
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/setup");
    expect(fetchImpl.mock.calls[0][1].method).toBe("GET");
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/setup/retry");
    expect(fetchImpl.mock.calls[1][1].method).toBe("POST");
    expect(fetchImpl.mock.calls[1][1].body).toBeUndefined();
  });

  it.each([
    { ready: true }, { progress: 101 }, { stage_progress: -1 }, { state: "healthy" },
    { downloaded_bytes: -1 }, { total_bytes: 1 }, { total_files: 0 }, { completed_files: 1.5 },
    { error_code: "C:\\private\\path" }, { updated_at: "not a timestamp" },
  ])("rejects invalid or contradictory progress %j", async (changes) => {
    const adapter = createApiAdapter({ fetchImpl: vi.fn().mockResolvedValue(response({ ...setup, ...changes })) });
    await expect(adapter.getSetup()).rejects.toMatchObject({ code: "CONTRACT_MISMATCH" });
  });

  it("allows unknown percentages and totals rather than fabricating them", async () => {
    const payload = { ...setup, progress: null, stage_progress: null, total_bytes: null };
    const adapter = createApiAdapter({ fetchImpl: vi.fn().mockResolvedValue(response(payload)) });
    expect(await adapter.getSetup()).toEqual(payload);
  });

  it("propagates component cancellation to the underlying request", async () => {
    let fetchSignal;
    const fetchImpl = vi.fn((url, options) => new Promise((resolve, reject) => {
      fetchSignal = options.signal;
      options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    const adapter = createApiAdapter({ fetchImpl });
    const controller = new AbortController();
    const request = adapter.getSetup({ signal: controller.signal });
    controller.abort();
    await expect(request).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(fetchSignal.aborted).toBe(true);
  });

  it("labels mock preparation explicitly and performs no installation", async () => {
    const adapter = createMockAdapter({});
    expect(await adapter.getSetup()).toMatchObject({ simulated: true, model: "simulated-local-model" });
    expect(await adapter.retrySetup()).toMatchObject({ simulated: true });
  });
});
