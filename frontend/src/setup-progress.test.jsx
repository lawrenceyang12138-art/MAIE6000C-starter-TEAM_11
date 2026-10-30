import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SetupProgress } from "./setup-progress.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const status = (state, extra = {}) => ({
  state, ready: state === "ready", progress: null, stage_progress: null,
  downloaded_bytes: 0, total_bytes: null, completed_files: 0, total_files: 0,
  model: "perplexity-ai/pplx-embed-v2-late-0.6b@pinned", message: "",
  error_code: null, retryable: false, updated_at: "2026-10-30T00:00:00Z", ...extra,
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};
let container, root;
beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});
async function render(adapter) {
  await act(async () => root.render(<><SetupProgress adapter={adapter} /><input aria-label="Keyword search" /></>));
}
async function advance(milliseconds) {
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds));
}

describe("local AI preparation progress", () => {
  it("shows reported download bytes and progress, then becomes ready without blocking the page", async () => {
    const adapter = {
      mode: "api",
      getSetup: vi.fn().mockResolvedValueOnce(status("downloading", {
        progress: 25, stage_progress: 50, downloaded_bytes: 1048576, total_bytes: 2097152,
        completed_files: 2, total_files: 14,
      })).mockResolvedValue(status("ready", { progress: 100 })),
    };
    await render(adapter);
    expect(container.textContent).toContain("Downloading the local PPLX model");
    expect(container.textContent).toContain("1.0 MiB / 2.0 MiB");
    expect(container.textContent).toContain("2 / 14 files");
    expect(container.querySelector("progress").getAttribute("value")).toBe("25");
    expect(container.querySelector("input").disabled).toBe(false);
    await advance(1000);
    expect(container.textContent).toContain("Local AI is ready");
    expect(container.textContent).toContain("verified and warmed up");
    expect(container.querySelector("progress")).toBeNull();
    await advance(9999);
    expect(adapter.getSetup).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(adapter.getSetup).toHaveBeenCalledTimes(3);
  });

  it("uses indeterminate progress when the backend has no percentage", async () => {
    const adapter = { mode: "api", getSetup: vi.fn().mockResolvedValue(status("loading")) };
    await render(adapter);
    expect(container.querySelector("progress").hasAttribute("value")).toBe(false);
    expect(container.textContent).toContain("progress is not yet known");
    expect(container.textContent).not.toContain("0% overall");
  });

  it("uses measured stage progress when the overall duration is unknown", async () => {
    const adapter = { mode: "api", getSetup: vi.fn().mockResolvedValue(status("verifying", { stage_progress: 75 })) };
    await render(adapter);
    expect(container.querySelector("progress").getAttribute("value")).toBe("75");
    expect(container.querySelector("progress").getAttribute("aria-label")).toBe("Current preparation stage progress");
    expect(container.textContent).toContain("75% of this stage");
    expect(container.textContent).not.toContain("75% overall");
  });

  it("retries only on explicit action, prevents duplicate POSTs, and resumes status reads", async () => {
    const accepted = deferred();
    const adapter = {
      mode: "api", retrySetup: vi.fn().mockReturnValue(accepted.promise),
      getSetup: vi.fn().mockResolvedValueOnce(status("error", { error_code: "model_download_failed", retryable: true }))
        .mockResolvedValue(status("downloading", { progress: 12 })),
    };
    await render(adapter);
    expect(container.textContent).toContain("model_download_failed");
    expect(adapter.retrySetup).not.toHaveBeenCalled();
    const button = container.querySelector("button");
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(adapter.retrySetup).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    await act(async () => accepted.resolve(status("downloading", { progress: 10 })));
    expect(container.textContent).toContain("Downloading the local PPLX model");
    expect(adapter.getSetup).toHaveBeenCalledTimes(2);
  });

  it("does not let an old poll overwrite an explicitly retried preparation", async () => {
    const oldRead = deferred();
    const adapter = {
      mode: "api", retrySetup: vi.fn().mockResolvedValue(status("downloading")),
      getSetup: vi.fn().mockResolvedValueOnce(status("error", { retryable: true }))
        .mockReturnValueOnce(oldRead.promise).mockResolvedValue(status("verifying")),
    };
    await render(adapter);
    await advance(10000);
    const oldSignal = adapter.getSetup.mock.calls[1][0].signal;
    await act(async () => container.querySelector("button").click());
    expect(oldSignal.aborted).toBe(true);
    await act(async () => oldRead.resolve(status("ready")));
    expect(container.textContent).toContain("Verifying model files");
    expect(container.textContent).not.toContain("Local AI is ready");
  });

  it("marks lost readiness unavailable and reconnects without replaying a failed retry", async () => {
    const adapter = {
      mode: "api", retrySetup: vi.fn().mockRejectedValue(new Error("uncertain POST")),
      getSetup: vi.fn().mockResolvedValueOnce(status("ready"))
        .mockRejectedValueOnce(new Error("lost service"))
        .mockResolvedValueOnce(status("error", { retryable: true }))
        .mockResolvedValue(status("warming_up")),
    };
    await render(adapter);
    await advance(10000);
    expect(container.textContent).toContain("Local AI service is unavailable");
    expect(container.textContent).not.toContain("Local AI is ready");
    expect(container.textContent).toContain("Keyword search and original source evidence remain available");
    await advance(10000);
    await act(async () => container.querySelector("button").click());
    expect(adapter.retrySetup).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Warming up local AI");
    await advance(1000);
    expect(adapter.retrySetup).toHaveBeenCalledTimes(1);
  });

  it("distinguishes disabled and unavailable states, without offering an inappropriate retry", async () => {
    const adapter = { mode: "api", getSetup: vi.fn().mockResolvedValue(status("disabled")) };
    await render(adapter);
    expect(container.textContent).toContain("Local AI is disabled");
    expect(container.querySelector("progress")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
    adapter.getSetup.mockResolvedValue(status("unavailable"));
    await advance(10000);
    expect(container.textContent).toContain("Local AI service is unavailable");
    expect(container.querySelector("button")).toBeNull();
  });

  it("aborts reads on unmount and ignores their late results without scheduling another poll", async () => {
    const pending = deferred();
    const adapter = { mode: "api", getSetup: vi.fn().mockReturnValue(pending.promise) };
    await render(adapter);
    const signal = adapter.getSetup.mock.calls[0][0].signal;
    await act(async () => root.unmount()); root = null;
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(status("ready")));
    await advance(20000);
    expect(adapter.getSetup).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("aborts a pending retry when the adapter changes and permits the new adapter to retry", async () => {
    const oldRetry = deferred(), nextRetry = deferred();
    const first = {
      mode: "api", getSetup: vi.fn().mockResolvedValue(status("error", { retryable: true })),
      retrySetup: vi.fn().mockReturnValue(oldRetry.promise),
    };
    const second = {
      mode: "api", getSetup: vi.fn().mockResolvedValue(status("error", { retryable: true })),
      retrySetup: vi.fn().mockReturnValue(nextRetry.promise),
    };
    await render(first);
    await act(async () => container.querySelector("button").click());
    const oldSignal = first.retrySetup.mock.calls[0][0].signal;
    await render(second);
    expect(oldSignal.aborted).toBe(true);
    expect(container.querySelector("button").disabled).toBe(false);
    await act(async () => container.querySelector("button").click());
    expect(second.retrySetup).toHaveBeenCalledTimes(1);
    await act(async () => oldRetry.resolve(status("ready")));
    expect(container.querySelector("button").disabled).toBe(true);
    expect(container.textContent).not.toContain("Local AI is ready");
    second.getSetup.mockResolvedValue(status("warming_up"));
    await act(async () => nextRetry.resolve(status("warming_up")));
    expect(container.textContent).toContain("Warming up local AI");
  });

  it("does not call the real status service or claim model readiness in mock mode", async () => {
    const adapter = { mode: "mock", getSetup: vi.fn(), retrySetup: vi.fn() };
    await render(adapter);
    await advance(20000);
    expect(adapter.getSetup).not.toHaveBeenCalled();
    expect(container.querySelector("section")).toBeNull();
  });
});
