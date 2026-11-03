import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdapterError } from "./api/errors.js";
import { LocalFolderAuthorization, LOCAL_FOLDER_STORAGE_KEY, hasUncertainScan } from "./local-folder-authorization.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const id = "1a0b6735-3aa7-4e0e-879c-d2af842bcc79";
const selected = { operation_id: id, state: "selected", folder_name: "Project files", display_path: "D:\\Project files" };
const ready = { ...selected, state: "ready", mount_id: "local-test" };
const accepted = { root_id: "root-local", job_id: 42, status: "pending" };
let container, root, localAdapter, adapter, onAccepted, onOpenResults, current;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => id) });
  window.sessionStorage.clear();
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
  current = selected;
  localAdapter = {
    getStatus: vi.fn().mockResolvedValue({ available: true }),
    startSelection: vi.fn(async () => current), getOperation: vi.fn(async () => current),
    prepare: vi.fn(async () => { current = { ...selected, state: "waiting" }; return current; }),
  };
  adapter = { createRootScan: vi.fn().mockResolvedValue(accepted), listRoots: vi.fn().mockResolvedValue([]) };
  onAccepted = vi.fn(); onOpenResults = vi.fn();
});

afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  window.sessionStorage.clear(); vi.useRealTimers(); vi.unstubAllGlobals();
});
async function render() { await act(async () => root.render(<LocalFolderAuthorization adapter={adapter} localAdapter={localAdapter} onAccepted={onAccepted} onOpenResults={onOpenResults} />)); }
function button(label) { return [...container.querySelectorAll("button")].find((item) => item.textContent === label); }
async function click(label) { await act(async () => button(label).click()); }
async function advance(ms = 1500) { await act(async () => vi.advanceTimersByTimeAsync(ms)); }

describe("Windows folder authorization", () => {
  it("shows the selected original path and requires authorization before preparing or scanning", async () => {
    await render(); await click("Choose local folder");
    expect(container.textContent).toContain("D:\\Project files");
    expect(container.textContent).toContain("Original files are never moved");
    expect(localAdapter.prepare).not.toHaveBeenCalled();
    expect(adapter.createRootScan).not.toHaveBeenCalled();
    expect(JSON.parse(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY))).toEqual({ operation_id: id });
  });

  it("clears a saved operation after the native dialog is cancelled asynchronously", async () => {
    current = { operation_id: id, state: "selecting" };
    await render(); await click("Choose local folder");
    expect(container.textContent).toContain("Choose a folder in the Windows dialog");
    current = { operation_id: id, state: "cancelled" };
    await advance();
    expect(container.textContent).toContain("No folder was authorized");
    expect(localAdapter.prepare).not.toHaveBeenCalled(); expect(adapter.createRootScan).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY)).toBeNull();
    expect(button("Choose local folder").disabled).toBe(false);
  });

  it("waits through busy jobs and API reconnection, then submits exactly one first scan", async () => {
    await render(); await click("Choose local folder");
    await act(async () => { const authorize = button("Authorize and start scan"); authorize.click(); authorize.click(); });
    expect(localAdapter.prepare).toHaveBeenCalledTimes(1);
    expect(adapter.createRootScan).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Waiting for the current file task");
    current = { ...selected, state: "reconnecting" }; await advance();
    expect(container.textContent).toContain("Reconnecting");
    current = ready; await advance();
    expect(adapter.createRootScan).toHaveBeenCalledTimes(1);
    expect(adapter.createRootScan).toHaveBeenCalledWith("local-test", ".");
    expect(onAccepted).toHaveBeenCalledWith(accepted);
    await advance(); expect(adapter.createRootScan).toHaveBeenCalledTimes(1);
  });

  it("resumes a saved operation using only reads after a page refresh", async () => {
    window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify({ operation_id: id }));
    current = { ...selected, state: "preparing" };
    await render();
    expect(localAdapter.getOperation).toHaveBeenCalledWith(id, expect.any(Object));
    expect(localAdapter.startSelection).not.toHaveBeenCalled(); expect(localAdapter.prepare).not.toHaveBeenCalled();
  });

  it("keeps polling the same operation when the chooser POST response is lost", async () => {
    localAdapter.startSelection.mockRejectedValueOnce(new Error("lost chooser response"));
    await render(); await click("Choose local folder"); await advance();
    expect(localAdapter.startSelection).toHaveBeenCalledTimes(1);
    expect(localAdapter.getOperation.mock.calls.every(([operationId]) => operationId === id)).toBe(true);
    expect(container.textContent).toContain("D:\\Project files");
    expect(adapter.createRootScan).not.toHaveBeenCalled();
  });

  it("restores interrupted preparation and explicitly retries with the same operation ID", async () => {
    window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify({ operation_id: id }));
    current = { ...selected, state: "failed", error_code: "preparation_interrupted" };
    await render(); await click("Retry preparation");
    expect(localAdapter.prepare).toHaveBeenCalledTimes(1);
    expect(localAdapter.prepare).toHaveBeenCalledWith(id);
    expect(localAdapter.startSelection).not.toHaveBeenCalled();
  });

  it("locks a lost first scan response and recovers current content using only root reads", async () => {
    adapter.createRootScan.mockRejectedValueOnce(new AdapterError("Connection lost", { status: 0, code: "NETWORK_ERROR" }));
    adapter.listRoots.mockResolvedValueOnce([]).mockResolvedValue([{ root_id: "root-local", mount_id: "local-test", relative_path: ".", status: "active" }]);
    await render(); await click("Choose local folder"); await click("Authorize and start scan");
    current = ready; await advance();
    expect(container.textContent).toContain("will not be replayed");
    expect(JSON.parse(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY)).scan_attempt).toEqual({ mount_id: "local-test", relative_path: "." });
    await advance(2000);
    expect(container.textContent).toContain("Scan acceptance is unconfirmed");
    expect(adapter.createRootScan).toHaveBeenCalledTimes(1);
    expect(hasUncertainScan("root-local")).toBe(true);
    await click("View current indexed content"); expect(onOpenResults).toHaveBeenCalledWith("root-local");
    expect(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY)).toBeNull();
    expect(hasUncertainScan("root-local")).toBe(true);
  });

  it("does not replay a persisted first scan attempt even if the helper reports ready", async () => {
    window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify({ operation_id: id, scan_attempt: { mount_id: "local-test", relative_path: "." } }));
    current = ready;
    await render(); await advance(5000);
    expect(adapter.createRootScan).not.toHaveBeenCalled();
    expect(localAdapter.prepare).not.toHaveBeenCalled(); expect(localAdapter.startSelection).not.toHaveBeenCalled();
    expect(adapter.listRoots).toHaveBeenCalled();
  });

  it("clears a missing saved selection and offers a fresh picker without submitting a scan", async () => {
    window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify({ operation_id: id }));
    localAdapter.getOperation.mockRejectedValue(new AdapterError("Selection unavailable", { status: 404, code: "LOCAL_FOLDER_NOT_FOUND" }));
    await render(); await advance();
    expect(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY)).toBeNull();
    expect(button("Choose local folder")).toBeTruthy();
    expect(container.textContent).not.toContain("Start the local folder service with");
    expect(localAdapter.startSelection).not.toHaveBeenCalled();
    expect(adapter.createRootScan).not.toHaveBeenCalled();
    await click("Choose local folder");
    expect(localAdapter.startSelection).toHaveBeenCalledTimes(1);
    expect(adapter.createRootScan).not.toHaveBeenCalled();
  });

  it("shows launcher instructions when the local service cannot be reached", async () => {
    localAdapter.getStatus.mockRejectedValue(new Error("Service unavailable"));
    await render();
    expect(container.textContent).toContain("python scripts/start.py");
    expect(button("Choose local folder").disabled).toBe(true);
  });

  it("explains that an unreachable saved picker result has not authorized or scanned a folder", async () => {
    window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify({ operation_id: id }));
    localAdapter.getOperation.mockRejectedValue(new AdapterError("Bridge unavailable", { status: 0, code: "LOCAL_FOLDER_UNAVAILABLE" }));
    await render();
    expect(container.textContent).toContain("Cannot check the previous folder selection");
    expect(container.textContent).toContain("Cancelling the picker does not grant access or start a scan");
    expect(localAdapter.prepare).not.toHaveBeenCalled();
    expect(adapter.createRootScan).not.toHaveBeenCalled();
  });

  it("offers an explicit scan retry after a definitive refusal without replaying it automatically", async () => {
    adapter.createRootScan.mockRejectedValueOnce(new AdapterError("Source unavailable", { status: 403, code: "SOURCE_UNAVAILABLE" }));
    await render(); await click("Choose local folder"); await click("Authorize and start scan");
    current = ready; await advance(); await advance(3000);
    expect(adapter.createRootScan).toHaveBeenCalledTimes(1);
    expect(adapter.listRoots).not.toHaveBeenCalled();
    expect(container.textContent).toContain("scan request was refused");
    expect(button("Choose another folder")).toBeTruthy();
    await click("Retry scan request");
    expect(adapter.createRootScan).toHaveBeenCalledTimes(2);
    expect(onAccepted).toHaveBeenCalledWith(accepted);
  });

  it("ignores a stale pre-authorization read after preparation starts", async () => {
    await render(); await click("Choose local folder");
    let resolveOldRead;
    localAdapter.getOperation.mockImplementationOnce(() => new Promise((resolve) => { resolveOldRead = resolve; }));
    await advance();
    await click("Authorize and start scan");
    await act(async () => resolveOldRead(selected));
    expect(container.textContent).toContain("Waiting for the current file task");
    expect(button("Authorize and start scan")).toBeUndefined();
  });
});
