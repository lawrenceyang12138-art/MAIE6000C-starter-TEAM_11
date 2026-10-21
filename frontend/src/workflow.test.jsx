import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdapterError } from "./api/errors.js";
import { RelationsPage } from "./relations-page.jsx";
import { useSearch } from "./lib/use-search.js";
import { RescanControl } from "./rescan-control.jsx";
import { RetryJobControl } from "./retry-job-control.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const file = { root_id: "root", file_id: "file", version_id: "version", relative_path: "manual.pdf", display_name: "manual.pdf", presence_status: "present", status: "basic_ready" };
const hit = { root_id: "root", file_id: "file", version_id: "version", file_path: "manual.pdf", chunk_id: "chunk", page: 1, ordinal: 1 };
const relation = { relationship_id: "rel", label: "Chen", entity_type: "person", relation_type: "mentions", origin: "rule", producer_revision: "rules-v1", quote: "Chen builds the assistant.", page_number: 1, evidence_missing: false, decision: null, corrected_entity_id: null, decision_revision: 0 };
const evidence = { ...hit, relative_path: "manual.pdf", page_number: 1, text: relation.quote, content_sha256: "a".repeat(64) };
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
let container, root;
beforeEach(() => {
  window.sessionStorage.setItem("lastRootId", "root");
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); window.sessionStorage.clear(); });
async function render(component) { await act(async () => root.render(component)); }
async function click(text) { await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === text).click()); }
async function fill(element, value) {
  await act(async () => {
    const prototype = element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, value);
    element.dispatchEvent(new Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}
function mockAdapter() {
  return { listFiles: vi.fn().mockResolvedValue([file]), listRelations: vi.fn().mockResolvedValue([relation]),
    search: vi.fn().mockResolvedValue({ results: [hit] }), getEvidenceByChunk: vi.fn().mockResolvedValue(evidence),
    recordReview: vi.fn().mockResolvedValue({ decision_revision: 1 }) };
}

describe("search request lifecycle", () => {
  let current;
  function Harness({ adapter, rootId = "root" }) {
    current = useSearch(adapter, rootId);
    return <div>{current.status}:{current.response?.query}</div>;
  }
  it("late results cannot overwrite a newer query", async () => {
    const first = deferred(), second = deferred();
    const adapter = { search: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise) };
    await render(<Harness adapter={adapter} />);
    let p1, p2;
    await act(async () => { p1 = current.run({ query: "first" }); p2 = current.run({ query: "second" }); });
    await act(async () => { second.resolve({ query: "second" }); await p2; });
    await act(async () => { first.resolve({ query: "first" }); await p1; });
    expect(container.textContent).toBe("success:second");
  });
  it("changing scope or clearing search invalidates an in-flight result", async () => {
    const pending = deferred(); const adapter = { search: () => pending.promise };
    await render(<Harness adapter={adapter} />);
    let request;
    await act(async () => { request = current.run({ query: "old scope" }); });
    await render(<Harness adapter={adapter} rootId="other" />);
    await act(async () => { pending.resolve({ query: "old scope" }); await request; });
    expect(container.textContent).toBe("idle:");
  });
});

describe("relation review workflow", () => {
  it("requires source verification and shows a decision only after the service accepts it", async () => {
    const adapter = mockAdapter(); const saved = deferred(); adapter.recordReview.mockReturnValue(saved.promise);
    await render(<RelationsPage adapter={adapter} review />);
    expect(container.textContent).toContain("Rule-derived candidate");
    expect(container.querySelector("fieldset").disabled).toBe(true);
    await click("Open source passage");
    expect(adapter.getEvidenceByChunk).toHaveBeenCalledWith("chunk");
    expect(container.querySelector("fieldset").disabled).toBe(false);
    await fill(container.querySelector("input"), "reviewer-D");
    const form = container.querySelector("form");
    await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(adapter.recordReview).toHaveBeenCalledTimes(1);
    expect(adapter.recordReview).toHaveBeenCalledWith("rel", expect.objectContaining({ decision: "confirmed", expectedRevision: 0, actor: "reviewer-D" }));
    expect(container.querySelector(".relation-state").textContent).toBe("Candidate");
    await act(async () => { saved.resolve({ decision_revision: 1 }); });
    expect(container.querySelector(".relation-state").textContent).toBe("Confirmed");
    expect(container.textContent).toContain("Revision 1");
    await click("Confirmed");
    expect(container.querySelectorAll(".relation-card")).toHaveLength(1);
    await click("Candidate");
    expect(container.querySelectorAll(".relation-card")).toHaveLength(0);
  });
  it("locks a conflicting review until the latest server revision is reloaded", async () => {
    const adapter = mockAdapter(); adapter.recordReview.mockRejectedValue(new AdapterError("Another review exists", { code: "review_conflict", status: 409 }));
    await render(<RelationsPage adapter={adapter} review />); await click("Open source passage");
    await fill(container.querySelector("input"), "reviewer-D");
    await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(container.querySelector("fieldset").disabled).toBe(true);
    expect(container.querySelector(".relation-state").textContent).toBe("Candidate");
    adapter.listRelations.mockResolvedValue([{ ...relation, decision: "rejected", decision_revision: 1 }]);
    await click("Reload latest candidates");
    expect(container.querySelector(".relation-state").textContent).toBe("Rejected");
    expect(container.querySelector("fieldset").disabled).toBe(true);
    expect(adapter.recordReview).toHaveBeenCalledTimes(1);
  });
  it("cannot review a quote that does not match its version-bound source", async () => {
    const adapter = mockAdapter(); adapter.getEvidenceByChunk.mockResolvedValue({ ...evidence, version_id: "old" });
    await render(<RelationsPage adapter={adapter} review />); await click("Open source passage");
    expect(container.querySelector("fieldset").disabled).toBe(true);
    expect(container.textContent).toContain("version_superseded");
    expect(container.querySelector("blockquote").textContent).not.toContain(relation.quote);
    expect(adapter.recordReview).not.toHaveBeenCalled();
  });
  it("hides the stored quote when a source check fails for a non-source error", async () => {
    const adapter = mockAdapter();
    adapter.getEvidenceByChunk.mockRejectedValue(new AdapterError("Service unavailable", { status: 503, code: "HTTP_503" }));
    await render(<RelationsPage adapter={adapter} review />);
    expect(container.querySelector("blockquote").textContent).toContain("Unverified candidate quote");
    await click("Open source passage");
    expect(container.querySelector("blockquote").textContent).toContain("could not be verified");
    expect(container.querySelector("blockquote").textContent).not.toContain(relation.quote);
    expect(container.querySelector("fieldset").disabled).toBe(true);
    expect(adapter.recordReview).not.toHaveBeenCalled();
  });
  it("distinguishes relation endpoint failure from a successful empty list", async () => {
    const adapter = mockAdapter(); adapter.listRelations.mockRejectedValue(new AdapterError("Route missing", { status: 404, code: "HTTP_404" }));
    await render(<RelationsPage adapter={adapter} />);
    expect(container.textContent).toContain("HTTP_404");
    expect(container.textContent).not.toContain("No relation candidates");
    adapter.listRelations.mockResolvedValue([]); await click("Retry relation read");
    expect(container.textContent).toContain("No relation candidates");
  });
});

describe("rescan action", () => {
  it("submits once, waits for 202 acceptance, then navigates to the accepted job", async () => {
    const accepted = deferred();
    const adapter = { rescanRoot: vi.fn().mockReturnValue(accepted.promise) };
    const onAccepted = vi.fn();
    await render(<RescanControl adapter={adapter} rootId="root" onAccepted={onAccepted} />);
    const button = container.querySelector("button");
    await act(async () => { button.click(); button.click(); });
    expect(adapter.rescanRoot).toHaveBeenCalledTimes(1);
    expect(adapter.rescanRoot).toHaveBeenCalledWith("root");
    expect(button.disabled).toBe(true);
    await act(async () => accepted.resolve({ root_id: "root", job_id: 7, status: "pending", status_code: 202 }));
    expect(onAccepted).toHaveBeenCalledWith(expect.objectContaining({ job_id: 7 }));
    expect(button.disabled).toBe(true);
  });

  it("does not replay a rescan after an uncertain server response", async () => {
    const adapter = { rescanRoot: vi.fn().mockRejectedValue(new AdapterError("Connection lost", { status: 0, code: "NETWORK_ERROR" })) };
    await render(<RescanControl adapter={adapter} rootId="root" onAccepted={vi.fn()} />);
    await click("Rescan directory");
    expect(container.querySelector("[role=alert]").textContent).toContain("NETWORK_ERROR");
    expect(container.textContent).toContain("will not be replayed");
    expect(container.querySelector("button").disabled).toBe(true);
  });
});

describe("failed job retry action", () => {
  const job = { job_id: "job-17", root_id: "root", status: "failed" };

  it("submits once and hands the accepted pending job back to progress", async () => {
    const accepted = deferred();
    const adapter = { retryJob: vi.fn().mockReturnValue(accepted.promise) };
    const onAccepted = vi.fn();
    await render(<RetryJobControl adapter={adapter} job={job} statusVersion={1} onAccepted={onAccepted} onRefresh={vi.fn()} />);
    const button = container.querySelector("button");
    await act(async () => { button.click(); button.click(); });
    expect(adapter.retryJob).toHaveBeenCalledTimes(1);
    expect(adapter.retryJob).toHaveBeenCalledWith("job-17", "root");
    expect(button.disabled).toBe(true);
    await act(async () => accepted.resolve({ job_id: "job-17", root_id: "root", status: "pending", status_code: 202 }));
    expect(onAccepted).toHaveBeenCalledWith(expect.objectContaining({ status: "pending" }));
  });

  it("does not replay a conflicted retry and stays locked until a fresh status read", async () => {
    const adapter = { retryJob: vi.fn().mockRejectedValue(new AdapterError("Job is no longer retryable", { status: 409, code: "HTTP_409" })) };
    const onRefresh = vi.fn();
    await render(<RetryJobControl adapter={adapter} job={job} statusVersion={1} onAccepted={vi.fn()} onRefresh={onRefresh} />);
    await click("Retry failed job");
    expect(adapter.retryJob).toHaveBeenCalledTimes(1);
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(container.querySelector("button").disabled).toBe(true);
    expect(container.textContent).toContain("No request was replayed");
    await render(<RetryJobControl adapter={adapter} job={job} statusVersion={2} onAccepted={vi.fn()} onRefresh={onRefresh} />);
    expect(container.querySelector("button").disabled).toBe(false);
    expect(adapter.retryJob).toHaveBeenCalledTimes(1);
  });
});
