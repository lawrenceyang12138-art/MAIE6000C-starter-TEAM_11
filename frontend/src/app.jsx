import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  ArrowUpRight,
  CheckCircle,
  FileText,
  FolderOpen,
  LockKey,
  WarningCircle,
} from "@phosphor-icons/react";
import { createAdapter } from "./api/adapter.js";
import { dedupeFiles, isEvidenceForVersion, isSourceUnavailable, shouldPoll, statusMeta, summarizeProgress } from "./lib/scan.js";

const adapter = createAdapter();

function navigate(path) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function useRoute() {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  return pathname;
}

function ActionButton({ children, className, ...props }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.button
      {...props}
      className={"action-button " + (className || "")}
      whileTap={reduceMotion || props.disabled ? undefined : { scale: 0.98 }}
      transition={reduceMotion ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 22 }}
    >
      {children}
    </motion.button>
  );
}

function StatusBadge({ status, label }) {
  const meta = statusMeta(status);
  return (
    <span className={"status-badge status-" + meta.tone}>
      <span className="status-dot" />
      {label || meta.label}
    </span>
  );
}

function ErrorNotice({ error }) {
  if (!error) return null;
  return (
    <div className="notice notice-danger" role="alert">
      <span className="notice-icon"><WarningCircle size={17} weight="fill" aria-hidden="true" /></span>
      <div>
        <strong>{error.message}</strong>
        <span>Error code: {error.code || "UNKNOWN_ERROR"} · {error.status ? "HTTP " + error.status : "No HTTP response"}</span>
      </div>
    </div>
  );
}

function Shell({ children, activeLabel, activeNav, inspector, rootId }) {
  const storedRoot = rootId || window.sessionStorage.getItem("lastRootId");
  const searchPath = storedRoot ? "/results/" + storedRoot : "/select";
  const navItems = [
    { key: "search", label: "Search & Discover", glyph: "⌕", path: searchPath },
    { key: "graph", label: "Knowledge Graph", glyph: "⌘", path: "/graph" },
    { key: "directories", label: "Directories & Jobs", glyph: "▤", path: "/select" },
    { key: "organize", label: "Organize & History", glyph: "⇄", path: "/organize" },
  ];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="side-rail" aria-label="Application navigation">
        <button className="brand" onClick={() => navigate(searchPath)} aria-label="Open Search and Discover">
          <span className="brand-mark" aria-hidden="true"><span>F</span><i /></span>
          <span className="brand-copy"><strong>File Trace</strong><small>LOCAL WORKSPACE</small></span>
        </button>
        <div className="engine-state">
          <span className="engine-dot" />
          <span><strong>{adapter.mode === "mock" ? "Simulated local engine" : "Local service mode"}</strong><small>{adapter.mode === "mock" ? "Demo data · not product evidence" : "API state must be verified"}</small></span>
        </div>
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="primary-nav">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={"nav-item " + (activeNav === item.key ? "active" : "")}
              onClick={() => navigate(item.path)}
              aria-current={activeNav === item.key ? "page" : undefined}
            >
              <span className="nav-glyph" aria-hidden="true">{item.glyph}</span>
              <span>{item.label}</span>
              {activeNav === item.key && <span className="nav-current" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-label">AUTHORIZED SCOPE</div>
          <div className="scope-item">
            <span className="scope-icon"><FolderOpen size={16} weight="duotone" /></span>
            <span><strong>Read-only configured mounts</strong><small>{adapter.mode === "mock" ? "Synthetic demonstration" : "Scope returned by API"}</small></span>
            <span className="scope-state" title="Active" />
          </div>
          <ActionButton className="scope-scan" onClick={() => navigate("/select")}><span>+</span> Authorize or scan</ActionButton>
          <div className="privacy-note"><LockKey size={14} weight="duotone" /><span>Original files stay on disk.<br />Host paths stay local.</span></div>
        </div>
      </aside>
      <header className="topbar">
        <div className="breadcrumbs"><span>WORKSPACE</span><span className="crumb-slash">/</span><strong>{activeLabel}</strong></div>
        <div className="topbar-right">
          <span className="offline-indicator"><i />{adapter.mode === "mock" ? "Simulation only" : "Local API · not health-verified"}</span>
          <span className={"mode-pill " + (adapter.mode === "mock" ? "mode-mock" : "mode-api")}>{adapter.mode === "mock" ? "Demo data" : "API mode"}</span>
          <span className="avatar" aria-label="Local user">T</span>
        </div>
      </header>
      <main className="page-wrap" id="main-content">
        {adapter.mode === "mock" && <div className="notice notice-info" role="note">SIMULATED CONTRACT DATA — not real backend, parser, model, or product acceptance evidence.</div>}
        {children}
      </main>
      <aside className={"inspector-pane " + (inspector ? "has-selection" : "")} aria-label="Context inspector">
        {inspector || (
          <div className="inspector-empty">
            <div className="inspector-empty-mark"><FileText size={21} weight="duotone" /></div>
            <h2>Context inspector</h2>
            <p>Select a file to inspect its source evidence, version and provenance.</p>
            <div className="inspector-hint"><span className="hint-key">⌘</span><span>Details stay in this workspace</span></div>
          </div>
        )}
      </aside>
      <footer className="footer">
        <span><span className="footer-dot" />Local-first · Read-only mounts · Evidence is version-bound</span>
        <span>CONTRACT <code>{adapter.mode === "mock" ? "d-mock-contract-v1" : "d-ui-integration-v1"}</code></span>
      </footer>
    </div>
  );
}

function PageHeading({ eyebrow, title, description, action }) {
  return (
    <div className="page-heading">
      <div className="heading-copy">
        <p className="meta-label">{eyebrow}</p>
        <h1>{title}</h1>
        {description && <p className="lede">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function SelectPage() {
  const [mounts, setMounts] = useState([]);
  const [directories, setDirectories] = useState([]);
  const [mountId, setMountId] = useState("");
  const [relativePath, setRelativePath] = useState("");
  const [accepted, setAccepted] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [directoriesLoading, setDirectoriesLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setMounts([]);
    setMountId("");
    setRelativePath("");
    setDirectories([]);
    setError(null);
    adapter.listMounts().then((items) => {
      if (cancelled) return;
      setMounts(items);
      if (items[0]) setMountId(items[0].mount_id);
    }).catch((caught) => { if (!cancelled) setError(caught); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reload]);

  useEffect(() => {
    if (!mountId) {
      setRelativePath("");
      setDirectories([]);
      setDirectoriesLoading(false);
      return undefined;
    }
    let cancelled = false;
    setRelativePath("");
    setDirectories([]);
    setDirectoriesLoading(true);
    setError(null);
    adapter.listDirectories(mountId).then((items) => {
      if (!cancelled) setDirectories(items);
    }).catch((caught) => {
      if (!cancelled) setError(caught);
    }).finally(() => {
      if (!cancelled) setDirectoriesLoading(false);
    });
    return () => { cancelled = true; };
  }, [mountId, reload]);

  async function submit(event) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    setAccepted(null);
    try {
      const response = await adapter.createRootScan(mountId, relativePath);
      setAccepted(response);
      window.sessionStorage.setItem("lastRootId", response.root_id);
      navigate("/scan/" + response.job_id);
    } catch (caught) {
      setError(caught);
    } finally { setSubmitting(false); }
  }

  return (
    <>
      <PageHeading
        eyebrow="DIRECTORIES & JOBS"
        title="Choose a local scope"
        description="Authorize a configured read-only mount, then queue its scan."
        action={<StatusBadge status="completed" label={adapter.mode === "mock" ? "Demo environment" : "API mode"} />}
      />
      <ErrorNotice error={error} />
      {error && <button className="secondary-button" onClick={() => setReload((value) => value + 1)}>Retry directory reads</button>}
      {!loading && !error && mounts.length === 0 && <div className="notice notice-info" role="status">No configured read-only mounts. Ask the service owner to configure an authorized source.</div>}
      {accepted && (
        <div className="notice notice-success" role="status" aria-live="polite">
          <CheckCircle size={18} weight="fill" />
          <div><strong>Scan job accepted</strong><span>Root {accepted.root_id} · Job {accepted.job_id} · Status {accepted.status}</span></div>
        </div>
      )}
      <div className="select-layout">
        <form className="workspace-panel glass-card authorization-panel" onSubmit={submit}>
          <div className="panel-topline"><div><span className="panel-icon"><LockKey size={17} weight="duotone" /></span><span>DIRECTORY AUTHORIZATION</span></div><span className="method-label">POST <code>/roots</code></span></div>
          <h2>Define the scan boundary</h2>
          <p className="panel-intro">Only a mount ID and a configured relative path are sent. The client never receives an absolute host path.</p>
          <label htmlFor="mount">Read-only mount</label>
          <select id="mount" value={mountId} onChange={(event) => setMountId(event.target.value)} disabled={loading} aria-describedby="mount-hint">
            {loading && mounts.length === 0 && <option value="">Loading approved mounts…</option>}
            {mounts.map((mount) => <option key={mount.mount_id} value={mount.mount_id}>{mount.label} · {mount.mount_id}</option>)}
          </select>
          <label htmlFor="directory">Configured directory</label>
          <select id="directory" value={relativePath} onChange={(event) => setRelativePath(event.target.value)} disabled={!directories.length || directoriesLoading} required>
            <option value="" disabled>{directoriesLoading ? "Loading configured directories…" : directories.length === 0 ? "No configured directories available" : "Select a directory"}</option>
            {directories.map((directory) => <option key={directory.relative_path} value={directory.relative_path}>{directory.label} · {directory.relative_path}</option>)}
          </select>
          <div className="form-hint" id="mount-hint"><LockKey size={16} weight="duotone" /><span>The mount is read-only. File enumeration and parsing happen asynchronously after this request.</span></div>
          <ActionButton className="primary-button" type="submit" disabled={!relativePath || loading || directoriesLoading || submitting}>{submitting ? "Waiting for acceptance…" : "Authorize and start scan"} <ArrowUpRight size={16} /></ActionButton>
        </form>
        <section className="workspace-panel glass-card contract-panel">
          <div className="panel-title-row"><div><p className="meta-label">REQUEST CONTRACT</p><h2>Scoped by design</h2></div><CheckCircle size={22} weight="fill" className="green-icon" /></div>
          <div className="contract-line"><span>Response</span><strong>202 Accepted</strong></div>
          <div className="contract-line"><span>Returns</span><code>root_id · job_id · pending</code></div>
          <div className="contract-line"><span>Access scope</span><StatusBadge status="completed" label="Read-only" /></div>
          <p className="contract-copy">Authorization queues a job. It does not enumerate, parse or analyze files in the request.</p>
          <div className="contract-foot"><span className="engine-dot" />Host paths stay on the server</div>
        </section>
      </div>
      <div className="safeguards-row">
        <div><span className="safeguard-mark">OK</span><span><strong>Configured mounts only</strong><small>Out-of-scope paths are rejected</small></span></div>
        <div><span className="safeguard-mark">↻</span><span><strong>Server-owned progress</strong><small>Job state is read, never mutated</small></span></div>
        <div><span className="safeguard-mark">⌂</span><span><strong>Originals untouched</strong><small>Read-only source access</small></span></div>
      </div>
    </>
  );
}

function StatStrip({ progress }) {
  const stats = summarizeProgress(progress);
  return (
    <div className="job-stats">
      <div><span>Files processed</span><strong>{stats.processed ?? "—"}<small> / {stats.total ?? "—"}</small></strong></div>
      <div><span>Searchable</span><strong className="tone-green">{stats.normal ?? "—"}</strong></div>
      <div><span>Failed</span><strong className="tone-rose">{stats.abnormal ?? "—"}</strong></div>
      <div><span>Unsupported</span><strong className="tone-amber">{stats.unsupported ?? "—"}</strong></div>
    </div>
  );
}

function ScanPage({ jobId }) {
  const [job, setJob] = useState(null);
  const [root, setRoot] = useState(null);
  const [error, setError] = useState(null);
  const [pollCount, setPollCount] = useState(0);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer;
    setJob(null);
    setRoot(null);
    setError(null);
    setPollCount(0);
    async function poll() {
      try {
        const next = await adapter.getJob(jobId);
        if (cancelled) return;
        setJob(next);
        const scope = await adapter.getRoot(next.root_id);
        if (cancelled) return;
        setRoot(scope);
        setError(null);
        setPollCount((count) => count + 1);
        if (shouldPoll(next, scope)) timer = window.setTimeout(poll, 900);
      } catch (caught) {
        if (!cancelled) { setRoot(null); setError(caught); }
      }
    }
    poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [jobId, reload]);

  const meta = statusMeta(job?.status || "pending");
  const progress = summarizeProgress(root);
  const stopped = ["failed", "canceled"].includes(job?.status);
  const terminalStatus = stopped ? job.status : "completed";
  const stageIndex = ["pending", "running", terminalStatus].indexOf(job?.status || "");
  const completed = job?.status === "completed";
  return (
    <>
      <PageHeading eyebrow="PROCESSING QUEUE" title="Scan progress" description={"Job " + jobId + " · Read-only polling of background execution"} action={<StatusBadge status={job?.status || "pending"} label={meta.label} />} />
      {job && (
        <div className={"notice " + (job.status === "failed" ? "notice-danger" : "notice-info")} role="status" aria-live="polite">
          <span className="notice-icon">{job.status === "failed" ? <WarningCircle size={18} weight="fill" /> : <CheckCircle size={18} weight="fill" />}</span>
          <div><strong>{job.status === "failed" ? "Scan job failed" : job.status === "canceled" ? "Scan job canceled" : "Scan job accepted"}</strong><span>Root {job.root_id} · Job {job.job_id} · Last read status {job.status}</span></div>
          <code>{job.error_code || ("Poll " + pollCount + " · attempt " + (job.attempts || 1))}</code>
        </div>
      )}
      <ErrorNotice error={error} />
      {error && <button className="secondary-button" onClick={() => setReload((value) => value + 1)}>Retry status reads</button>}
      {root?.availability && root.availability !== "available" && <div className="notice notice-danger" role="alert">Source unavailable. Existing cached results do not prove the source is accessible.</div>}
      {completed && <div className="notice notice-info" role="status">Scan discovery complete — extraction and AI are separate. {progress.known ? progress.pending + " files still awaiting processing." : "File counters unavailable; processing readiness is unknown."}</div>}
      <section className="workspace-panel glass-card progress-panel">
        <div className="progress-head"><div><p className="meta-label">SCAN JOB · ROOT</p><h2>{job?.root_id || (error ? "Job status unavailable" : "Connecting to scan job")}</h2></div><span className="poll-count">{job ? "Updated on poll " + pollCount : "Waiting for first response"}</span></div>
        {job && root ? (
          <>
            {progress.known ? <><div className="progress-track" role="progressbar" aria-label="File processing progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress.percent}><span style={{ transform: "scaleX(" + (progress.percent / 100) + ")" }} /></div><div className="progress-caption"><strong>{progress.percent}%</strong><span>{progress.processed} of {progress.total} files processed · {progress.pending} pending</span></div></> : <div className="state-message">File counters unavailable. No readiness is inferred from scan status.</div>}
            <StatStrip progress={root} />
          </>
        ) : error ? <div className="state-message state-error">Progress could not be loaded. Review the error above, then reopen this scan link.</div> : <div className="loading-state"><span className="loading-bar" /><span>Fetching committed job status…</span></div>}
      </section>
      <section className="workspace-panel glass-card timeline-panel">
        <div className="panel-title-row"><div><p className="meta-label">BACKGROUND WORKER</p><h2>Job lifecycle</h2></div><span className="lifecycle-note">Scan completion ≠ parse completion</span></div>
        <div className="timeline">
          {[
            ["pending", "Accepted", "202 response issued"],
            ["running", "Scanning", "Worker enumerates files"],
            [terminalStatus, stopped ? "Stopped" : "Discovery complete", stopped ? "Check the job status and failure code" : "File processing tracked separately"],
          ].map(([status, title, detail], index) => (
            <div className={"timeline-item " + (index < stageIndex ? "complete " : "") + (index === stageIndex ? "active " : "") + (index === stageIndex && terminalStatus === "failed" ? "failed" : "")} key={status + index} aria-current={index === stageIndex ? "step" : undefined}>
              <span className="timeline-marker" /><div><strong>{title}</strong><small>{detail}</small></div>
            </div>
          ))}
        </div>
        {job?.root_id && <ActionButton className="primary-button" onClick={() => { window.sessionStorage.setItem("lastRootId", job.root_id); navigate("/results/" + job.root_id); }}>View available files and evidence <ArrowUpRight size={16} /></ActionButton>}
      </section>
      <div className="state-boundary"><LockKey size={17} /><span><strong>Read-only status</strong><small>The API returns committed state. This client never submits job lifecycle values.</small></span></div>
    </>
  );
}

function Inspector({ data }) {
  const [tab, setTab] = useState("evidence");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setTab("evidence");
    setCopied(false);
  }, [data?.file?.file_id, data?.file?.version_id]);
  useEffect(() => {
    function closeOnEscape(event) {
      if (event.key === "Escape") data?.onClose?.();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [data?.onClose]);
  if (!data?.file) return null;
  const { file, evidence, evidenceError, evidenceLoading } = data;
  const invalidSource = isSourceUnavailable(file, evidenceError);
  const status = file.status === "failed" ? "failed_file" : file.status;
  const meta = statusMeta(status);
  async function copyPath() {
    try {
      await navigator.clipboard.writeText(file.relative_path);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="inspector-content reveal-on-load">
      <div className="inspector-heading"><div><p className="meta-label">FILE INSPECTOR</p><h2>Source context</h2></div><div className="inspector-close-wrap"><kbd>ESC</kbd><button className="inspector-close" onClick={data.onClose} aria-label="Close inspector">×</button></div></div>
      <div className="inspector-file-head"><span className={"inspector-file-icon tone-" + meta.tone}><FileText size={19} weight="duotone" /></span><div><strong>{file.display_name}</strong><StatusBadge status={status} /></div></div>
      <div className="path-block"><div className="path-label"><span>LOCAL PATH</span><button onClick={copyPath}>{copied ? "Copied" : "Copy"}</button></div><code>{file.relative_path}</code></div>
      <div className="inspector-tabs" role="tablist" aria-label="File details">
        {[["evidence", "Evidence"], ["entities", "Entities"], ["metadata", "Metadata"]].map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "selected" : ""} onClick={() => setTab(key)}>{label}</button>)}
      </div>
      {tab === "evidence" && (
        <div className="inspector-tab-content">
          <div className="evidence-section-title"><span>Indexed passage</span><span className="evidence-locator">{file.page_count ? file.page_count + " source pages" : "No locator"}</span></div>
          <div className="passage-card"><span className="passage-quote">“</span><p>{invalidSource ? "Cached passage hidden until the source is verified." : file.snippet || "No indexed passage available."}</p><small>{file.scan_note}</small></div>
          {invalidSource && <div className="stale-warning"><WarningCircle size={16} /><span>Source file unavailable or changed. Re-check the mounted directory.</span></div>}
          {file.capability_status === "keyword_only" && <div className="fallback-note">Keyword-only mode · semantic enrichment unavailable</div>}
          <div className="evidence-detail-heading"><strong>Version evidence</strong><code>{file.version_id}</code></div>
          {invalidSource ? <>{evidenceError && <ErrorNotice error={evidenceError} />}<p className="muted-copy">Source evidence is hidden until the current source is verified.</p></> : evidenceLoading ? <div className="loading-line">Loading version-bound evidence…</div> : evidenceError ? <ErrorNotice error={evidenceError} /> : evidence?.length ? evidence.map((item) => <div className="evidence-record" key={item.evidence_id}><span className="page-index">P{item.page}</span><div><strong>{item.source_path}</strong><p>{item.excerpt}</p></div></div>) : <p className="muted-copy">{file.page_count === 0 ? "No page evidence is available for this file." : "Open the source evidence to load its version-bound passages."}</p>}
          <button className="subtle-button" disabled>Open local preview <span>Not available in this adapter</span></button>
        </div>
      )}
      {tab === "entities" && (
        <div className="inspector-tab-content">
          <div className="placeholder-state"><span className="placeholder-symbol">◇</span><strong>No relationship data in this adapter</strong><p>Entity extraction, graph edges and human review are not exposed by the current service contract.</p></div>
          <div className="contract-note"><strong>Review actions are unavailable</strong><span>Confirm, correct and reject controls will appear when a review endpoint is available.</span></div>
        </div>
      )}
      {tab === "metadata" && (
        <div className="inspector-tab-content metadata-list">
          {[
            ["File ID", file.file_id],
            ["Content version", file.version_id],
            ["Fingerprint", file.sha256],
            ["File status", file.status],
            ["Pages", String(file.page_count)],
            ["Capability", file.capability_status],
            ["Source", file.source_kind],
            ["Last scan note", file.scan_note],
          ].map(([label, value]) => <div key={label}><span>{label}</span><code>{value || "—"}</code></div>)}
        </div>
      )}
    </div>
  );
}

function ResultsPage({ rootId, onInspector }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState(null);
  const [evidence, setEvidence] = useState({});
  const [evidenceErrors, setEvidenceErrors] = useState({});
  const [evidenceLoading, setEvidenceLoading] = useState({});
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [reload, setReload] = useState(0);
  const searchInput = useRef(null);
  const generation = useRef(0);

  useEffect(() => {
    let cancelled = false;
    generation.current += 1;
    setLoading(true);
    setFiles([]);
    setError(null);
    setSelectedKey(null);
    setEvidence({});
    setEvidenceErrors({});
    setEvidenceLoading({});
    adapter.listFiles(rootId).then((items) => {
      if (!cancelled) setFiles(dedupeFiles(items));
    }).catch((caught) => {
      if (!cancelled) setError(caught);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; generation.current += 1; };
  }, [rootId, reload]);

  const selected = files.find((file) => file.file_id + ":" + file.version_id === selectedKey) || null;
  useEffect(() => {
    onInspector(selected ? {
      file: selected,
      evidence: evidence[selectedKey],
      evidenceError: evidenceErrors[selectedKey],
      evidenceLoading: Boolean(evidenceLoading[selectedKey]),
      onClose: () => setSelectedKey(null),
    } : null);
  }, [selected, selectedKey, evidence, evidenceErrors, evidenceLoading, onInspector]);

  useEffect(() => {
    function focusSearch(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
      }
    }
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  async function selectFile(file) {
    const requestGeneration = generation.current;
    const key = file.file_id + ":" + file.version_id;
    setSelectedKey(key);
    if (isSourceUnavailable(file) || evidence[key] || evidenceErrors[key] || file.page_count === 0) return;
    setEvidenceLoading((current) => ({ ...current, [key]: true }));
    try {
      const items = await adapter.getEvidence(file.file_id, file.version_id);
      if (generation.current !== requestGeneration) return;
      if (!isEvidenceForVersion(items, file.file_id, file.version_id, { sourcePath: file.relative_path, pageCount: file.page_count })) throw new Error("The evidence file, version, source path or page does not match the current result.");
      setEvidence((current) => ({ ...current, [key]: items }));
    } catch (caught) {
      if (generation.current !== requestGeneration) return;
      setEvidenceErrors((current) => ({ ...current, [key]: caught }));
    } finally {
      if (generation.current === requestGeneration) setEvidenceLoading((current) => ({ ...current, [key]: false }));
    }
  }

  const counts = useMemo(() => files.reduce((result, file) => {
    if (["basic_ready", "enriched"].includes(file.status)) result.ready += 1;
    if (file.status === "failed") result.failed += 1;
    if (file.status === "unsupported") result.unsupported += 1;
    return result;
  }, { ready: 0, failed: 0, unsupported: 0 }), [files]);
  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((file) => {
      const invalidSource = isSourceUnavailable(file, evidenceErrors[file.file_id + ":" + file.version_id]);
      const matchesQuery = !needle || [file.display_name, file.relative_path, file.file_id, invalidSource ? "" : file.snippet, file.scan_note].some((value) => String(value || "").toLowerCase().includes(needle));
      const matchesFilter = filter === "all" || (filter === "ready" && ["basic_ready", "enriched"].includes(file.status)) || (filter === "attention" && !["basic_ready", "enriched"].includes(file.status));
      return matchesQuery && matchesFilter;
    });
  }, [files, query, filter, evidenceErrors]);

  return (
    <>
      <PageHeading eyebrow="SEARCH & DISCOVER" title="Find in your files" description={rootId + " · Current versions with traceable source evidence"} action={<button className="secondary-button" disabled={loading} onClick={() => setReload((value) => value + 1)}>Refresh current versions</button>} />
      <div className="search-field spotlight-field"><span className="search-glyph">⌕</span><input ref={searchInput} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter loaded filenames, relative paths and available snippets…" aria-label="Filter loaded files" /><kbd>⌘ K</kbd></div>
      <div className="search-telemetry" aria-live="polite">
        <span className="telemetry-led" />
        <span>{loading ? "Loading file records" : error ? "File records unavailable" : "Found " + filteredFiles.length + " matching files"}</span>
        <span className="telemetry-separator">·</span>
        <span>{loading ? "Preparing evidence" : (counts.failed + counts.unsupported) + " attention items"}</span>
        <span className="telemetry-separator">·</span>
        <span className="telemetry-ready">{loading ? "Reading service state" : error ? "Check local API" : "Client-side filter · not semantic search"}</span>
      </div>
      <div className="filter-row" aria-label="File filters">
        {[["all", "All files"], ["ready", "Ready"], ["attention", "Needs attention"]].map(([key, label]) => <button key={key} className={filter === key ? "filter-chip selected" : "filter-chip"} onClick={() => setFilter(key)}>{label}{key === "all" && !loading && <span>{files.length}</span>}{key === "ready" && !loading && <span>{counts.ready}</span>}{key === "attention" && !loading && <span>{counts.failed + counts.unsupported}</span>}</button>)}
        <span className="filter-separator" />
        <span className="filter-summary">{loading ? "Loading files…" : filteredFiles.length + " results"}</span>
      </div>
      <ErrorNotice error={error} />
      <div className="result-overview glass-card">
        <div><span>SEARCHABLE</span><strong className="tone-green">{loading || error ? "—" : counts.ready}</strong></div>
        <div><span>FAILED</span><strong className="tone-rose">{loading || error ? "—" : counts.failed}</strong></div>
        <div><span>UNSUPPORTED</span><strong className="tone-amber">{loading || error ? "—" : counts.unsupported}</strong></div>
        <div className="overview-note"><span className="overview-led" /><span>Evidence is tied to a specific content version</span></div>
      </div>
      <section className="results-panel glass-card">
        <div className="results-header"><div><h2>Files</h2><p>Matched passages and processing state</p></div><span className="results-count">{loading ? "Loading" : filteredFiles.length + " of " + files.length}</span></div>
        {loading ? <div className="results-loading" role="status"><span className="loading-bar" /><span>Loading current file versions…</span></div> : error ? <div className="empty-state"><FolderOpen size={30} /><h3>Results unavailable</h3><p>Check the request error above and reopen this view.</p></div> : files.length === 0 ? <div className="empty-state"><FolderOpen size={30} /><h3>No indexed files yet</h3><p>Authorize a configured directory and complete a scan to populate this workspace.</p><ActionButton className="secondary-button" onClick={() => navigate("/select")}>Authorize local directory</ActionButton></div> : filteredFiles.length === 0 ? <div className="empty-state"><h3>No matches found</h3><p>Try a broader phrase or clear the current filters.</p><button className="text-button" onClick={() => { setQuery(""); setFilter("all"); }}>Clear search and filters</button></div> : (
          <div className="file-list">
            {filteredFiles.map((file, index) => {
              const key = file.file_id + ":" + file.version_id;
              const invalidSource = isSourceUnavailable(file, evidenceErrors[key]);
              const tone = file.status === "failed" ? "rose" : file.status === "unsupported" ? "amber" : "indigo";
              const status = statusMeta(file.status === "failed" ? "failed_file" : file.status);
              return (
                <motion.article key={key} style={{ "--stagger-index": Math.min(index, 7) }} className={"file-row motion-stagger " + (selectedKey === key ? "selected" : "")} layout transition={{ duration: 0.18 }}>
                  <button className="file-row-main" onClick={() => selectFile(file)} aria-pressed={selectedKey === key}>
                    <span className={"document-icon doc-" + tone}><FileText size={18} weight="duotone" /></span>
                    <span className="file-main-copy"><strong>{file.display_name}</strong><code>{file.relative_path}</code></span>
                    <StatusBadge status={file.status === "failed" ? "failed_file" : file.status} label={status.label} />
                    <span className="file-open">Inspect <ArrowUpRight size={14} /></span>
                  </button>
                  <div className="file-row-details">
                    <div className="file-match"><span className="match-label">FILE STATE</span><strong>{invalidSource ? "Source unavailable · verify before inspecting evidence" : ["basic_ready", "enriched"].includes(file.status) ? "Indexed record · inspect version-bound evidence" : file.status === "failed" ? "Processing stopped · filename remains visible" : file.status === "unsupported" ? "Format not supported · filename remains visible" : "Processing is not yet complete"}</strong></div>
                    <div className="file-passage"><span className="quote-mark">“</span><span>{invalidSource ? "Cached passage hidden until the source is verified." : file.snippet}</span><code className="passage-locator">{file.page_count ? file.page_count + " source pages · inspect to locate passage" : file.expected_error_code || file.error_code || "No page locator"}</code></div>
                    <div className="file-meta-line"><span><i className={"tiny-state " + (["basic_ready", "enriched"].includes(file.status) ? "confirmed" : file.status === "failed" ? "failed" : "paused")} />{["basic_ready", "enriched"].includes(file.status) ? "Indexed source" : file.status === "failed" ? "Action needed" : file.status === "unsupported" ? "Unsupported format" : "Processing pending"}</span><span className="file-version">ID {file.file_id} · {file.version_id}</span></div>
                    {(invalidSource || file.capability_status === "keyword_only" || file.expected_error_code || file.error_code) && <div className={"file-warning " + (file.status === "failed" ? "warning-danger" : "")}>{file.expected_error_code || file.error_code || (invalidSource ? "Source file unavailable or changed" : "Keyword-only search capability")}</div>}
                  </div>
                </motion.article>
              );
            })}
          </div>
        )}
      </section>
      <div className="results-footnote"><LockKey size={15} /><span>Search is limited to authorized local scopes. No file contents or activity leave this device.</span></div>
    </>
  );
}

function UnavailablePage({ kind }) {
  const graph = kind === "graph";
  return (
    <>
      <PageHeading
        eyebrow={graph ? "KNOWLEDGE GRAPH" : "ORGANIZE & HISTORY"}
        title={graph ? "Explore connected knowledge" : "Plan safe file operations"}
        description={graph ? "Local relationships and source-backed context will appear here." : "Preview every change before explicit approval. Original files remain untouched until execution is available."}
        action={<span className="status-badge status-neutral">Adapter unavailable</span>}
      />
      <section className={"workspace-panel glass-card unavailable-panel bg-dot-grid " + (graph ? "graph-empty" : "organize-empty")}>
        <div className="unavailable-mark">{graph ? "◇" : "⇄"}</div>
        <div>
          <h2>{graph ? "Graph data is not exposed yet" : "No organization endpoint is available"}</h2>
          <p>{graph ? "The current adapter exposes mounts, directories, scan jobs, files and version-bound evidence. It does not provide graph or entity-review data." : "The current adapter has no propose, execute, history or undo endpoints. This view is intentionally read-only and will not simulate file operations."}</p>
          <button className="secondary-button" onClick={() => navigate("/select")}>Open directories and jobs <ArrowUpRight size={15} /></button>
        </div>
      </section>
      <div className="placeholder-contract"><strong>Not connected to the current service contract</strong><span>No mock confirmation, file mutation or fabricated relationship is shown.</span></div>
    </>
  );
}

export default function App() {
  const pathname = useRoute();
  const [inspectorData, setInspectorData] = useState(null);
  const activeRoot = pathname.startsWith("/results/") ? decodeURIComponent(pathname.slice("/results/".length)) : null;
  useEffect(() => {
    setInspectorData(null);
  }, [pathname]);
  const setInspector = useCallback((data) => setInspectorData(data), []);
  let page;
  let activeLabel = "Directories & Jobs";
  let activeNav = "directories";
  if (pathname.startsWith("/scan/")) {
    activeLabel = "Processing queue";
    page = <ScanPage jobId={decodeURIComponent(pathname.slice("/scan/".length))} />;
  } else if (pathname.startsWith("/results/")) {
    activeLabel = "Search & Discover";
    activeNav = "search";
    page = <ResultsPage rootId={activeRoot} onInspector={setInspector} />;
  } else if (pathname === "/graph") {
    activeLabel = "Knowledge Graph";
    activeNav = "graph";
    page = <UnavailablePage kind="graph" />;
  } else if (pathname === "/organize") {
    activeLabel = "Organize & History";
    activeNav = "organize";
    page = <UnavailablePage kind="organize" />;
  } else {
    page = <SelectPage />;
  }
  return <Shell activeLabel={activeLabel} activeNav={activeNav} inspector={inspectorData ? <Inspector data={inspectorData} /> : null} rootId={activeRoot}>{page}</Shell>;
}
