import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring } from "framer-motion";
import {
  ArrowUpRight,
  CaretDown,
  CaretUp,
  CheckCircle,
  FileText,
  FolderOpen,
  LockKey,
  WarningCircle,
} from "@phosphor-icons/react";
import { createAdapter } from "./api/adapter.js";
import { dedupeFiles, isEvidenceForVersion, statusMeta, summarizeProgress } from "./lib/scan.js";

const adapter = createAdapter();

function MagneticButton({ children, className, ...props }) {
  const shouldReduceMotion = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const springX = useSpring(x, { stiffness: 100, damping: 20, mass: 0.4 });
  const springY = useSpring(y, { stiffness: 100, damping: 20, mass: 0.4 });

  function move(event) {
    if (props.disabled || shouldReduceMotion) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    x.set((event.clientX - (bounds.left + bounds.width / 2)) * 0.08);
    y.set((event.clientY - (bounds.top + bounds.height / 2)) * 0.08);
  }

  function reset() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.button
      {...props}
      className={className}
      style={{ x: springX, y: springY }}
      onPointerMove={move}
      onPointerLeave={reset}
      whileTap={shouldReduceMotion ? undefined : { scale: 0.98 }}
      transition={shouldReduceMotion ? { duration: 0 } : { type: "spring", stiffness: 100, damping: 20 }}
    >
      {children}
    </motion.button>
  );
}

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

function Shell({ children, activeStep, activeLabel }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="side-rail" aria-label="Application navigation">
        <button className="brand" onClick={() => navigate("/select")} aria-label="Return to directory selection">
          <span className="brand-mark" aria-hidden="true"><span>11</span></span>
          <span className="brand-copy">
            <strong>File Trace</strong>
            <small>TEAM 11 <span aria-hidden="true">/</span> W07</small>
          </span>
        </button>
        <div className="sidebar-rule" />
        <div className="sidebar-section-label">WORKFLOW</div>
        <StepRail active={activeStep} />
        <div className="sidebar-spacer" />
        <div className="sidebar-note">
          <span className="sidebar-note-icon"><LockKey size={17} weight="duotone" aria-hidden="true" /></span>
          <span className="sidebar-note-label">SAFE BY DESIGN</span>
          <p>Approved mounts only. Host paths stay on the server.</p>
        </div>
        <div className="sidebar-foot">FILE OPERATIONS <span>·</span> MIDTERM DEMO</div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><span>FILE TRACE</span><span className="breadcrumb-separator">/</span><strong>{activeLabel}</strong></div>
          <div className="topbar-meta">
            <span className="environment-label">DATA ENVIRONMENT</span>
            <span className="environment-pill"><span className="mode-dot" />{adapter.mode === "mock" ? "Mock data" : "API mode"}</span>
          </div>
        </header>
        <main className="page-wrap" id="main-content">{children}</main>
        <footer className="footer">
          <span>Read-only mounts <span>·</span> Traceable evidence <span>·</span> Job status is not parse completion</span>
          <span>CONTRACT <code>d-mock-contract-v1</code></span>
        </footer>
      </div>
    </div>
  );
}

function PageHeading({ eyebrow, title, description, action }) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {description && <p className="lede">{description}</p>}
      </div>
      {action}
    </div>
  );
}

function ErrorNotice({ error }) {
  if (!error) return null;
  return (
    <div className="notice notice-danger" role="alert">
      <div>
        <strong>{error.message}</strong>
        <span>Error code: {error.code || "UNKNOWN_ERROR"} · HTTP {error.status || 500}</span>
      </div>
      <span className="notice-action">Fix the issue and retry</span>
    </div>
  );
}

function StepRail({ active }) {
  const steps = [
    ["01", "Select directory", "/select"],
    ["02", "Scan progress", null],
    ["03", "View evidence", null],
  ];
  return (
    <nav className="step-rail" aria-label="Demo steps">
      {steps.map(([number, label, path], index) => {
        const className = `step ${active === index ? "active" : active > index ? "complete" : ""}`;
        const content = <><span className="step-number">{number}</span><span className="step-copy"><strong>{label}</strong><small>{index === 0 ? "Set a safe scope" : index === 1 ? "Follow the background job" : "Inspect versions and pages"}</small></span>{active === index && <span className="step-current">CURRENT</span>}</>;
        return path ? (
          <button className={className} onClick={() => navigate(path)} aria-current={active === index ? "step" : undefined} key={number}>
            {content}
          </button>
        ) : (
          <div className={className} aria-current={active === index ? "step" : undefined} key={number}>
            {content}
          </div>
        );
      })}
    </nav>
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
    adapter
      .listMounts()
      .then((items) => {
        setMounts(items);
        if (items[0]) setMountId(items[0].mount_id);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!mountId) return;
    let cancelled = false;
    setRelativePath("");
    setDirectories([]);
    setDirectoriesLoading(true);
    setError(null);
    adapter
      .listDirectories(mountId)
      .then((items) => {
        if (!cancelled) setDirectories(items);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught);
      })
      .finally(() => {
        if (!cancelled) setDirectoriesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mountId]);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setAccepted(null);
    try {
      const response = await adapter.createRootScan(mountId, relativePath);
      setAccepted(response);
      window.sessionStorage.setItem("lastRootId", response.root_id);
      navigate(`/scan/${response.job_id}`);
    } catch (caught) {
      setError(caught);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="10.14 · 10.15 / DIRECTORY INTAKE"
        title="Choose a read-only directory"
        description="Set the authorization boundary first, then queue a scan. The request submits only the mount ID and relative path; the client never receives an absolute host path."
        action={<span className="status-chip chip-info">{adapter.mode === "mock" ? "MOCK DATA" : "API MODE"}</span>}
      />
      <ErrorNotice error={error} />
      {accepted && (
        <div className="notice notice-success" role="status" aria-live="polite">
          <div>
            <strong><CheckCircle className="inline-icon" size={15} weight="bold" aria-hidden="true" />202 Accepted · Scan job queued</strong>
            <span>Root ID {accepted.root_id} · Job ID {accepted.job_id} · Status {accepted.status}</span>
          </div>
          <span className="notice-action">Opening progress view...</span>
        </div>
      )}
      <section className="content-grid select-grid">
        <form className="surface form-card" onSubmit={submit}>
          <div className="form-heading">
            <span className="surface-kicker">AUTHORIZATION REQUEST</span>
            <span className="request-method">POST <code>/roots</code></span>
          </div>
          <h2 className="form-title">Define the scan boundary</h2>
          <p className="form-description">Choose an approved mount and a relative directory to begin.</p>
          <label htmlFor="mount">Read-only mount</label>
          <select id="mount" value={mountId} onChange={(event) => setMountId(event.target.value)} disabled={loading} aria-describedby="mount-hint">
            {loading && mounts.length === 0 && <option value="">Loading approved mounts…</option>}
            {mounts.map((mount) => (
              <option key={mount.mount_id} value={mount.mount_id}>
                {mount.label} · {mount.mount_id}
              </option>
            ))}
          </select>
          <label htmlFor="directory">Relative directory</label>
          <select id="directory" value={relativePath} onChange={(event) => setRelativePath(event.target.value)} disabled={!directories.length || directoriesLoading} required>
            <option value="" disabled>
              {directoriesLoading ? "Loading configured directories…" : directories.length === 0 ? "No configured directories available" : "Select a configured directory"}
            </option>
            {directories.map((directory) => (
              <option key={directory.relative_path} value={directory.relative_path}>
                {directory.label} · {directory.relative_path}
              </option>
            ))}
          </select>
          <div className="form-hint" id="mount-hint">
            <LockKey className="lock-icon" size={16} weight="duotone" aria-hidden="true" />
            The selected mount is read-only. The API does not enumerate, parse, or analyze files during the POST request.
          </div>
          <MagneticButton className="primary-button" type="submit" disabled={!relativePath || loading}>
            Authorize and start scan <ArrowUpRight className="button-icon" size={16} aria-hidden="true" />
          </MagneticButton>
        </form>
        <aside className="surface contract-card">
          <div className="contract-header">
            <div className="surface-kicker">REQUEST CONTRACT</div>
            <span className="contract-seal" aria-hidden="true"><CheckCircle size={18} weight="fill" /></span>
          </div>
          <div className="contract-row"><span>Response</span><strong>202 Accepted</strong></div>
          <div className="contract-row"><span>Returns</span><code>root_id · job_id · pending</code></div>
          <div className="contract-row"><span>Access scope</span><span className="inline-status good">Read-only</span></div>
          <div className="contract-rule" />
          <p>This request authorizes a directory and queues a job. File enumeration, parsing, and evidence retrieval happen in later steps.</p>
          <div className="contract-footnote"><span className="mode-dot" />Host paths stay on the server</div>
        </aside>
      </section>
      <section className="micro-grid" aria-label="Workflow safeguards">
        <div className="micro-card"><span className="micro-index">01</span><div><strong>Scoped access</strong><small>Configured mounts only · 403 / 404</small></div></div>
        <div className="micro-card"><span className="micro-index">02</span><div><strong>Separate job state</strong><small>Authorization is not scan completion</small></div></div>
        <div className="micro-card"><span className="micro-index">03</span><div><strong>Server-owned progress</strong><small>Poll status · never mutate it in the client</small></div></div>
      </section>
    </>
  );
}

function StatStrip({ progress }) {
  const stats = summarizeProgress(progress);
  return (
    <div className="stat-strip">
      <div><span>Processed</span><strong>{stats.processed}<em> / {stats.total}</em></strong></div>
      <div><span>Normal</span><strong className="text-good">{stats.normal}</strong></div>
      <div><span>Abnormal</span><strong className="text-danger">{stats.abnormal}</strong></div>
      <div><span>Unsupported</span><strong className="text-warning">{stats.unsupported}</strong></div>
      <div className="stat-percent"><span>Completion</span><strong>{stats.percent}%</strong></div>
    </div>
  );
}

function ScanPage({ jobId }) {
  const shouldReduceMotion = useReducedMotion();
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
        if (next.status !== "completed" && next.status !== "failed") {
          timer = window.setTimeout(poll, 900);
        }
      } catch (caught) {
        if (!cancelled) setError(caught);
      }
    }
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  const meta = statusMeta(job?.status || "pending");
  const progress = job ? summarizeProgress(job) : null;
  const isDone = job?.status === "completed";
  const terminalStatus = job?.status === "failed" ? "failed" : "completed";
  const stageOrder = ["pending", "running", terminalStatus];
  const stageIndex = stageOrder.indexOf(job?.status || "");

  return (
    <>
      <PageHeading
        eyebrow="10.15 / SCAN MONITOR"
        title="Scan progress and job status"
        description={`Job ${jobId} · Read-only polling of background execution`}
        action={<span className={`status-chip chip-${meta.tone}`}>{meta.label}</span>}
      />
      {job && (
        <div className={`notice ${job.status === "failed" ? "notice-danger" : "notice-success"}`} role="status" aria-live="polite">
          <div>
            <strong>{job.status === "failed" ? <WarningCircle className="inline-icon" size={15} weight="bold" aria-hidden="true" /> : <CheckCircle className="inline-icon" size={15} weight="bold" aria-hidden="true" />}{job.status === "failed" ? "Scan job failed" : "202 Accepted · Scan job accepted"}</strong>
            <span>Root ID {job.root_id} · Job ID {job.job_id} · Current status {job.status}</span>
          </div>
          <span className="notice-action">{job.status === "failed" ? job.error_code || "Review the job error" : "Asynchronous processing"}</span>
        </div>
      )}
      <ErrorNotice error={error} />
      <section className="surface progress-hero">
        <div className="progress-title-row">
          <div>
            <div className="surface-kicker">SCAN JOB <span className="kicker-divider">/</span> ROOT</div>
            <h2>{job?.root_id || (error ? "Job status unavailable" : "Connecting to scan job")}</h2>
          </div>
          <div className="poll-note">{job ? `Poll ${pollCount} · attempt ${job.attempts || 1}` : "Waiting for first status response"}</div>
        </div>
        {job ? (
          <>
            <div className="progress-bar" role="progressbar" aria-label="Scan progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress.percent}><span style={{ transform: `scaleX(${progress.percent / 100})` }} /></div>
            <div className="progress-caption"><strong>{progress.percent}%</strong><span>{progress.processed} / {progress.total} files observed</span></div>
            <StatStrip progress={job} />
          </>
        ) : error ? (
          <div className="progress-unavailable" role="status">Progress could not be loaded. Review the error above, then reopen the scan link.</div>
        ) : (
          <div className="progress-skeleton" role="status" aria-live="polite" aria-label="Loading scan progress">
            <span className="skeleton skeleton-progress" />
            <div className="skeleton-stat-row">{[0, 1, 2, 3, 4].map((item) => <span className="skeleton skeleton-stat" key={item} />)}</div>
            <span className="loading-caption">Fetching committed job status…</span>
          </div>
        )}
      </section>
      <div className="callout-grid">
        <div className="notice notice-info">
          <div><strong>State boundary</strong><span>Scan Job completion does not mean every file has finished parsing or AI enrichment.</span></div>
        </div>
        <div className="notice notice-neutral">
          <div><strong>Data path</strong><span>The API returns committed state; the client never sends running / completed status fields.</span></div>
        </div>
      </div>
      <motion.section className="surface timeline-card" layout={!shouldReduceMotion} transition={shouldReduceMotion ? { duration: 0 } : { type: "spring", stiffness: 100, damping: 20 }}>
        <div className="surface-kicker">OBSERVED EVENTS</div>
        <div className="timeline">
          {[
            ["pending", "Job accepted", "202 Accepted · root and job IDs issued"],
            ["running", "Worker scanning files", "12 normal / 3 abnormal / 1 unsupported"],
            [terminalStatus, terminalStatus === "failed" ? "Scan stopped" : "Results available", terminalStatus === "failed" ? `The scan ended with ${job?.error_code || "an execution error"}.` : "Evidence pages and versions are traceable"],
          ].map(([status, title, detail], index) => {
            const active = index === stageIndex;
            const complete = stageIndex > index;
            return <div className={`timeline-item ${active ? "active" : ""} ${complete ? "complete" : ""} ${active && terminalStatus === "failed" ? "failed" : ""}`} aria-current={active ? "step" : undefined} key={status}><span className="timeline-dot" /><div><strong>{title}</strong><small>{detail}</small></div></div>;
          })}
        </div>
        {isDone && <MagneticButton className="primary-button compact" onClick={() => navigate(`/results/${job.root_id}`)}>View results and evidence <ArrowUpRight className="button-icon" size={16} aria-hidden="true" /></MagneticButton>}
      </motion.section>
    </>
  );
}

function ResultsPage({ rootId }) {
  const shouldReduceMotion = useReducedMotion();
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [evidence, setEvidence] = useState({});
  const [error, setError] = useState(null);
  const [evidenceErrors, setEvidenceErrors] = useState({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFiles([]);
    setError(null);
    setExpanded(null);
    setEvidence({});
    setEvidenceErrors({});
    adapter
      .listFiles(rootId)
      .then((items) => {
        if (!cancelled) setFiles(dedupeFiles(items));
      })
      .catch((caught) => {
        if (!cancelled) setError(caught);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [rootId]);

  async function toggleEvidence(file) {
    const key = `${file.file_id}:${file.version_id}`;
    if (expanded === key) {
      setExpanded(null);
      return;
    }
    setExpanded(key);
    if (evidence[key] || file.page_count === 0) return;
    try {
      const items = await adapter.getEvidence(file.file_id, file.version_id);
      if (!isEvidenceForVersion(items, file.file_id, file.version_id)) {
        throw new Error("The evidence version does not match the result.");
      }
      setEvidence((current) => ({ ...current, [key]: items }));
    } catch (caught) {
      setEvidenceErrors((current) => ({ ...current, [key]: caught }));
    }
  }

  const counts = useMemo(() => files.reduce((result, file) => {
    if (file.status === "basic_ready") result.normal += 1;
    if (file.status === "failed") result.abnormal += 1;
    if (file.status === "unsupported") result.unsupported += 1;
    return result;
  }, { normal: 0, abnormal: 0, unsupported: 0 }), [files]);

  return (
    <>
      <PageHeading
        eyebrow="10.15 / RESULTS & EVIDENCE"
        title="Results and source evidence"
        description={`${rootId} · Deduplicated current versions with visible failure reasons`}
        action={<span className="status-chip chip-success">EVIDENCE READY</span>}
      />
      <ErrorNotice error={error} />
      <section className="stat-strip result-stats">
        <div><span>Total files</span><strong>{loading ? "—" : files.length}</strong></div>
        <div><span>Normal</span><strong className="text-good">{loading ? "—" : counts.normal}</strong></div>
        <div><span>Abnormal</span><strong className="text-danger">{loading ? "—" : counts.abnormal}</strong></div>
        <div><span>Unsupported</span><strong className="text-warning">{loading ? "—" : counts.unsupported}</strong></div>
        <div className="stat-percent"><span>Version policy</span><strong>{loading ? "Loading" : "Deduplicated"}</strong></div>
      </section>
      <section className="surface result-table-card">
        <div className="table-header"><div><div className="surface-kicker">FILE EVIDENCE INDEX</div><h2>File processing results</h2></div><span className="table-count">{loading ? "Loading records" : `${files.length} records`}</span></div>
        {loading ? (
          <div className="result-skeleton-list" role="status" aria-live="polite" aria-label="Loading file results">
            {[0, 1, 2, 3].map((item) => <div className="result-skeleton" key={item}><span className="skeleton skeleton-name" /><span className="skeleton skeleton-chip" /><span className="skeleton skeleton-meta" /></div>)}
            <span className="loading-caption">Loading current file versions…</span>
          </div>
        ) : error ? (
          <div className="empty-state unavailable-state"><FolderOpen className="empty-icon" size={34} weight="duotone" aria-hidden="true" /><h3>Results are unavailable</h3><p>The request failed. Check the message above and try opening the results again.</p></div>
        ) : files.length === 0 ? (
          <div className="empty-state"><FolderOpen className="empty-icon" size={34} weight="duotone" aria-hidden="true" /><h3>No results to display</h3><p>The directory is empty, or the scan has not produced file versions yet.</p><MagneticButton className="secondary-button" type="button" onClick={() => navigate("/select")}>Back to directory selection</MagneticButton></div>
        ) : (
          <div className="result-list">
            {files.map((file) => {
              const key = `${file.file_id}:${file.version_id}`;
              const meta = statusMeta(file.status === "failed" ? "failed_file" : file.status);
              const isOpen = expanded === key;
              return (
                <motion.article className={`result-row ${isOpen ? "open" : ""}`} key={key} layout={!shouldReduceMotion} transition={shouldReduceMotion ? { duration: 0 } : { type: "spring", stiffness: 100, damping: 20 }}>
                  <div className="result-main">
                    <div className="result-name"><span className={`file-icon ${meta.tone}`}><FileText size={17} weight="duotone" aria-hidden="true" /></span><div><strong>{file.display_name}</strong><small>{file.relative_path}</small></div></div>
                    <span className={`status-chip chip-${meta.tone}`}>{meta.label}</span>
                    <div className="result-field"><span>FILE ID</span><code>{file.file_id}</code></div>
                    <div className="result-field"><span>VERSION</span><code>{file.version_id}</code></div>
                    <div className="result-field"><span>PAGES</span><strong>{file.page_count || "-"}</strong></div>
                    <button className="evidence-button" onClick={() => toggleEvidence(file)} disabled={file.page_count === 0} aria-expanded={isOpen} aria-controls={`evidence-${file.file_id}-${file.version_id}`}>{isOpen ? <>Collapse evidence <CaretUp size={14} weight="bold" aria-hidden="true" /></> : file.source_available === false ? <>Check source <ArrowUpRight size={14} weight="bold" aria-hidden="true" /></> : <>Expand evidence <CaretDown size={14} weight="bold" aria-hidden="true" /></>}</button>
                  </div>
                  <div className="result-detail"><span className="detail-label">SNIPPET</span><span>{file.snippet}</span><span className="detail-label">STATE NOTE</span><span>{file.scan_note}{file.source_available === false && <span className="state-tag tag-danger">SOURCE MISSING</span>}{file.capability_status === "keyword_only" && <span className="state-tag tag-warning">KEYWORD ONLY</span>}</span>{file.expected_error_code && <span className="error-code">{file.expected_error_code}</span>}</div>
                  <AnimatePresence initial={false}>
                    {isOpen && (
                      <motion.div
                        className="evidence-panel"
                        id={`evidence-${file.file_id}-${file.version_id}`}
                        initial={shouldReduceMotion ? false : { opacity: 0, y: 7 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={shouldReduceMotion ? { opacity: 0 } : { opacity: 0, y: 7 }}
                        transition={shouldReduceMotion ? { duration: 0 } : { type: "spring", stiffness: 100, damping: 20 }}
                      >
                        {evidenceErrors[key] ? <ErrorNotice error={evidenceErrors[key]} /> : evidence[key] ? evidence[key].map((item) => <div className="evidence-item" key={item.evidence_id}><span className="page-badge">P{item.page}</span><div><strong>{item.source_path}</strong><p>{item.excerpt}</p></div><code>{item.version_id}</code></div>) : <div className="loading-line" role="status" aria-live="polite">Loading version evidence...</div>}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.article>
              );
            })}
          </div>
        )}
      </section>
      <div className="notice notice-info bottom-note"><div><strong>Evidence contract</strong><span>Every evidence item carries file_id, version_id, source_path, and page to prevent stale cache from being displayed.</span></div></div>
    </>
  );
}

export default function App() {
  const pathname = useRoute();
  let page;
  let activeStep = 0;
  let activeLabel = "Directory authorization";
  if (pathname.startsWith("/scan/")) {
    activeStep = 1;
    activeLabel = "Scan progress";
    page = <ScanPage jobId={decodeURIComponent(pathname.slice("/scan/".length))} />;
  } else if (pathname.startsWith("/results/")) {
    activeStep = 2;
    activeLabel = "Results & evidence";
    page = <ResultsPage rootId={decodeURIComponent(pathname.slice("/results/".length))} />;
  } else {
    page = <SelectPage />;
  }
  return <Shell activeStep={activeStep} activeLabel={activeLabel}>{page}</Shell>;
}
