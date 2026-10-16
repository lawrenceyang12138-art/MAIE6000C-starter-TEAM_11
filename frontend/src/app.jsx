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
import { dedupeFiles, isEvidenceForVersion, statusMeta, summarizeProgress } from "./lib/scan.js";

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
      className={className}
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
        <span>Error code: {error.code || "UNKNOWN_ERROR"} · HTTP {error.status || 500}</span>
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
          <span><strong>Local engine ready</strong><small>Offline safe · {adapter.mode === "mock" ? "Demo data" : "API connected"}</small></span>
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
            <span><strong>Team 11 demo mount</strong><small>Read-only · synthetic data</small></span>
            <span className="scope-state" title="Active" />
          </div>
          <ActionButton className="scope-scan" onClick={() => navigate("/select")}><span>+</span> Authorize or scan</ActionButton>
          <div className="privacy-note"><LockKey size={14} weight="duotone" /><span>Original files stay on disk.<br />Host paths stay local.</span></div>
        </div>
      </aside>
      <header className="topbar">
        <div className="breadcrumbs"><span>WORKSPACE</span><span className="crumb-slash">/</span><strong>{activeLabel}</strong></div>
        <div className="topbar-right">
          <span className="offline-indicator"><i />Offline ready</span>
          <span className={"mode-pill " + (adapter.mode === "mock" ? "mode-mock" : "mode-api")}>{adapter.mode === "mock" ? "Demo data" : "API mode"}</span>
          <span className="avatar" aria-label="Local user">T</span>
        </div>
      </header>
      <main className="page-wrap" id="main-content">{children}</main>
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
        <span>CONTRACT <code>d-mock-contract-v1</code></span>
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

  useEffect(() => {
    adapter.listMounts().then((items) => {
      setMounts(items);
      if (items[0]) setMountId(items[0].mount_id);
    }).catch(setError).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!mountId) return undefined;
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
  }, [mountId]);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setAccepted(null);
    try {
      const response = await adapter.createRootScan(mountId, relativePath);
      setAccepted(response);
      window.sessionStorage.setItem("lastRootId", response.root_id);
      navigate("/scan/" + response.job_id);
    } catch (caught) {
      setError(caught);
    }
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
      {accepted && (
        <div className="notice notice-success" role="status" aria-live="polite">
          <CheckCircle size={18} weight="fill" />
          <div><strong>Scan job accepted</strong><span>Root {accepted.root_id} · Job {accepted.job_id} · Status {accepted.status}</span></div>
        </div>
      )}
      <div className="select-layout">
        <form className="workspace-panel authorization-panel" onSubmit={submit}>
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
          <ActionButton className="primary-button" type="submit" disabled={!relativePath || loading}>Authorize and start scan <ArrowUpRight size={16} /></ActionButton>
        </form>
        <section className="workspace-panel contract-panel">
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
      <div><span>Files observed</span><strong>{stats.processed}<small> / {stats.total}</small></strong></div>
      <div><span>Searchable</span><strong className="tone-green">{stats.normal}</strong></div>
      <div><span>Failed</span><strong className="tone-rose">{stats.abnormal}</strong></div>
      <div><span>Unsupported</span><strong className="tone-amber">{stats.unsupported}</strong></div>
    </div>
  );
}

function ScanPage({ jobId }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer;
    async function poll() {
      try {
        const next = await adapter.getJob(jobId);
        if (cancelled) return;
        setJob(next);
        setPollCount((count) => count + 1);
        if (next.status !== "completed" && next.status !== "failed") timer = window.setTimeout(poll, 900);
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    }
    poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [jobId]);

  const meta = statusMeta(job?.status || "pending");
  const progress = job ? summarizeProgress(job) : null;
  const terminalStatus = job?.status === "failed" ? "failed" : "completed";
  const stageIndex = ["pending", "running", terminalStatus].indexOf(job?.status || "");
  const completed = job?.status === "completed";
  return (
    <>
      <PageHeading eyebrow="PROCESSING QUEUE" title="Scan progress" description={"Job " + jobId + " · Read-only polling of background execution"} action={<StatusBadge status={job?.status || "pending"} label={meta.label} />} />
      {job && (
        <div className={"notice " + (job.status === "failed" ? "notice-danger" : "notice-info")} role="status" aria-live="polite">
          <span className="notice-icon">{job.status === "failed" ? <WarningCircle size={18} weight="fill" /> : <CheckCircle size={18} weight="fill" />}</span>
          <div><strong>{job.status === "failed" ? "Scan job failed" : "Scan job accepted"}</strong><span>Root {job.root_id} · Job {job.job_id} · Current status {job.status}</span></div>
          <code>{job.error_code || ("Poll " + pollCount + " · attempt " + (job.attempts || 1))}</code>
        </div>
      )}
      <ErrorNotice error={error} />
      <section className="workspace-panel progress-panel">
        <div className="progress-head"><div><p className="meta-label">SCAN JOB · ROOT</p><h2>{job?.root_id || (error ? "Job status unavailable" : "Connecting to scan job")}</h2></div><span className="poll-count">{job ? "Updated on poll " + pollCount : "Waiting for first response"}</span></div>
        {job ? (
          <>
            <div className="progress-track" role="progressbar" aria-label="Scan progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress.percent}><span style={{ transform: "scaleX(" + (progress.percent / 100) + ")" }} /></div>
            <div className="progress-caption"><strong>{progress.percent}%</strong><span>{progress.processed} of {progress.total} files observed</span></div>
            <StatStrip progress={job} />
          </>
        ) : error ? <div className="state-message state-error">Progress could not be loaded. Review the error above, then reopen this scan link.</div> : <div className="loading-state"><span className="loading-bar" /><span>Fetching committed job status…</span></div>}
      </section>
      <section className="workspace-panel timeline-panel">
        <div className="panel-title-row"><div><p className="meta-label">BACKGROUND WORKER</p><h2>Job lifecycle</h2></div><span className="lifecycle-note">Scan completion ≠ parse completion</span></div>
        <div className="timeline">
          {[
            ["pending", "Accepted", "202 response issued"],
            ["running", "Scanning", "Worker enumerates files"],
            [terminalStatus, job?.status === "failed" ? "Stopped" : "Complete", job?.status === "failed" ? job.error_code || "Execution error" : "Results are ready"],
          ].map(([status, title, detail], index) => (
            <div className={"timeline-item " + (index < stageIndex ? "complete " : "") + (index === stageIndex ? "active " : "") + (index === stageIndex && terminalStatus === "failed" ? "failed" : "")} key={status + index} aria-current={index === stageIndex ? "step" : undefined}>
              <span className="timeline-marker" /><div><strong>{title}</strong><small>{detail}</small></div>
            </div>
          ))}
        </div>
        {completed && <ActionButton className="primary-button" onClick={() => { window.sessionStorage.setItem("lastRootId", job.root_id); navigate("/results/" + job.root_id); }}>View results and evidence <ArrowUpRight size={16} /></ActionButton>}
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
  if (!data?.file) return null;
  const { file, evidence, evidenceError, evidenceLoading } = data;
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
    <div className="inspector-content">
      <div className="inspector-heading"><div><p className="meta-label">FILE INSPECTOR</p><h2>Source context</h2></div><button className="inspector-close" onClick={data.onClose} aria-label="Close inspector">×</button></div>
      <div className="inspector-file-head"><span className={"inspector-file-icon tone-" + meta.tone}><FileText size={19} weight="duotone" /></span><div><strong>{file.display_name}</strong><StatusBadge status={status} /></div></div>
      <div className="path-block"><div className="path-label"><span>LOCAL PATH</span><button onClick={copyPath}>{copied ? "Copied" : "Copy"}</button></div><code>{file.relative_path}</code></div>
      <div className="inspector-tabs" role="tablist" aria-label="File details">
        {[["evidence", "Evidence"], ["entities", "Entities"], ["metadata", "Metadata"]].map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "selected" : ""} onClick={() => setTab(key)}>{label}</button>)}
      </div>
      {tab === "evidence" && (
        <div className="inspector-tab-content">
          <div className="evidence-section-title"><span>Matched source</span><span className="evidence-locator">{file.page_count ? "Page 1 · " + file.page_count + " page" + (file.page_count === 1 ? "" : "s") : "No locator"}</span></div>
          <div className="passage-card"><span className="passage-quote">“</span><p>{file.snippet}</p><small>{file.scan_note}</small></div>
          {file.source_available === false && <div className="stale-warning"><WarningCircle size={16} /><span>Source file unavailable. Re-check the mounted directory.</span></div>}
          {file.capability_status === "keyword_only" && <div className="fallback-note">Keyword-only mode · semantic enrichment unavailable</div>}
          <div className="evidence-detail-heading"><strong>Version evidence</strong><code>{file.version_id}</code></div>
          {evidenceLoading ? <div className="loading-line">Loading version-bound evidence…</div> : evidenceError ? <ErrorNotice error={evidenceError} /> : evidence?.length ? evidence.map((item) => <div className="evidence-record" key={item.evidence_id}><span className="page-index">P{item.page}</span><div><strong>{item.source_path}</strong><p>{item.excerpt}</p></div></div>) : <p className="muted-copy">{file.page_count === 0 ? "No page evidence is available for this file." : "Open the source evidence to load its version-bound passages."}</p>}
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
  const searchInput = useRef(null);

  useEffect(() => {
    let cancelled = false;
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
    return () => { cancelled = true; };
  }, [rootId]);

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
    const key = file.file_id + ":" + file.version_id;
    setSelectedKey(key);
    if (evidence[key] || evidenceErrors[key] || file.page_count === 0) return;
    setEvidenceLoading((current) => ({ ...current, [key]: true }));
    try {
      const items = await adapter.getEvidence(file.file_id, file.version_id);
      if (!isEvidenceForVersion(items, file.file_id, file.version_id)) throw new Error("The evidence version does not match the result.");
      setEvidence((current) => ({ ...current, [key]: items }));
    } catch (caught) {
      setEvidenceErrors((current) => ({ ...current, [key]: caught }));
    } finally {
      setEvidenceLoading((current) => ({ ...current, [key]: false }));
    }
  }

  const counts = useMemo(() => files.reduce((result, file) => {
    if (file.status === "basic_ready") result.ready += 1;
    if (file.status === "failed") result.failed += 1;
    if (file.status === "unsupported") result.unsupported += 1;
    return result;
  }, { ready: 0, failed: 0, unsupported: 0 }), [files]);
  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((file) => {
      const matchesQuery = !needle || [file.display_name, file.relative_path, file.file_id, file.snippet, file.scan_note].some((value) => String(value || "").toLowerCase().includes(needle));
      const matchesFilter = filter === "all" || (filter === "ready" && file.status === "basic_ready") || (filter === "attention" && file.status !== "basic_ready");
      return matchesQuery && matchesFilter;
    });
  }, [files, query, filter]);

  return (
    <>
      <PageHeading eyebrow="SEARCH & DISCOVER" title="Find in your files" description={rootId + " · Current versions with traceable source evidence"} action={<span className="scope-chip"><span />Authorized scope</span>} />
      <div className="search-field"><span className="search-glyph">⌕</span><input ref={searchInput} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by concept, topic, person, or keyword across authorized folders…" aria-label="Search files" /><kbd>⌘ K</kbd></div>
      <div className="filter-row" aria-label="File filters">
        {[["all", "All files"], ["ready", "Ready"], ["attention", "Needs attention"]].map(([key, label]) => <button key={key} className={filter === key ? "filter-chip selected" : "filter-chip"} onClick={() => setFilter(key)}>{label}{key === "all" && !loading && <span>{files.length}</span>}{key === "ready" && !loading && <span>{counts.ready}</span>}{key === "attention" && !loading && <span>{counts.failed + counts.unsupported}</span>}</button>)}
        <span className="filter-separator" />
        <span className="filter-summary">{loading ? "Loading files…" : filteredFiles.length + " results"}</span>
      </div>
      <ErrorNotice error={error} />
      <div className="result-overview">
        <div><span>SEARCHABLE</span><strong className="tone-green">{loading ? "—" : counts.ready}</strong></div>
        <div><span>FAILED</span><strong className="tone-rose">{loading ? "—" : counts.failed}</strong></div>
        <div><span>UNSUPPORTED</span><strong className="tone-amber">{loading ? "—" : counts.unsupported}</strong></div>
        <div className="overview-note"><span className="overview-led" /><span>Evidence is tied to a specific content version</span></div>
      </div>
      <section className="results-panel">
        <div className="results-header"><div><h2>Files</h2><p>Matched passages and processing state</p></div><span className="results-count">{loading ? "Loading" : filteredFiles.length + " of " + files.length}</span></div>
        {loading ? <div className="results-loading" role="status"><span className="loading-bar" /><span>Loading current file versions…</span></div> : error ? <div className="empty-state"><FolderOpen size={30} /><h3>Results unavailable</h3><p>Check the request error above and reopen this view.</p></div> : files.length === 0 ? <div className="empty-state"><FolderOpen size={30} /><h3>No indexed files yet</h3><p>Authorize a configured directory and complete a scan to populate this workspace.</p><ActionButton className="secondary-button" onClick={() => navigate("/select")}>Authorize local directory</ActionButton></div> : filteredFiles.length === 0 ? <div className="empty-state"><h3>No matches found</h3><p>Try a broader phrase or clear the current filters.</p><button className="text-button" onClick={() => { setQuery(""); setFilter("all"); }}>Clear search and filters</button></div> : (
          <div className="file-list">
            {filteredFiles.map((file) => {
              const key = file.file_id + ":" + file.version_id;
              const tone = file.status === "failed" ? "rose" : file.status === "unsupported" ? "amber" : "indigo";
              const status = statusMeta(file.status === "failed" ? "failed_file" : file.status);
              return (
                <motion.article key={key} className={"file-row " + (selectedKey === key ? "selected" : "")} layout transition={{ duration: 0.18 }}>
                  <button className="file-row-main" onClick={() => selectFile(file)} aria-pressed={selectedKey === key}>
                    <span className={"document-icon doc-" + tone}><FileText size={18} weight="duotone" /></span>
                    <span className="file-main-copy"><strong>{file.display_name}</strong><code>{file.relative_path}</code></span>
                    <StatusBadge status={file.status === "failed" ? "failed_file" : file.status} label={status.label} />
                    <span className="file-open">Inspect <ArrowUpRight size={14} /></span>
                  </button>
                  <div className="file-row-details">
                    <div className="file-match"><span className="match-label">MATCH REASON</span><strong>{file.status === "basic_ready" ? "Matched via indexed source passage" : file.status === "failed" ? "Processing stopped · fallback to filename search" : "Format not supported · filename remains searchable"}</strong></div>
                    <div className="file-passage"><span className="quote-mark">“</span><span>{file.snippet}</span><code>{file.page_count ? "Page 1 · " + file.page_count + " page" + (file.page_count === 1 ? "" : "s") : file.expected_error_code || "No page locator"}</code></div>
                    <div className="file-meta-line"><span><i className={"tiny-state " + (file.status === "basic_ready" ? "confirmed" : file.status === "failed" ? "failed" : "paused")} />{file.status === "basic_ready" ? "Source supported" : file.status === "failed" ? "Action needed" : "Unsupported format"}</span><span className="file-version">ID {file.file_id} · {file.version_id}</span></div>
                    {(file.source_available === false || file.capability_status === "keyword_only" || file.expected_error_code) && <div className={"file-warning " + (file.status === "failed" ? "warning-danger" : "")}>{file.expected_error_code || (file.source_available === false ? "Source file unavailable" : "Keyword-only search capability")}</div>}
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
      <section className="workspace-panel unavailable-panel">
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
