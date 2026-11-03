import { useCallback, useEffect, useRef, useState } from "react";
import { FolderOpen, LockKey } from "@phosphor-icons/react";
import { createLocalFolderAdapter } from "./api/local-folder-adapter.js";

export const LOCAL_FOLDER_STORAGE_KEY = "filetrace.localFolderOperation";
const recoveryKey = (rootId) => "filetrace.scanRecovery." + rootId;
const bridge = createLocalFolderAdapter();
const preparationStates = new Set(["waiting", "preparing", "reconnecting"]);
const messages = {
  selecting: "Choose a folder in the Windows dialog.",
  selected: "Review the folder below, then authorize read-only access.",
  waiting: "Waiting for the current file task to finish before adding this folder…",
  preparing: "Preparing read-only access to your folder…",
  reconnecting: "Reconnecting the local file service…",
  ready: "Your folder is ready for scanning.",
  cancelled: "Folder selection cancelled. No folder was authorized.",
  failed: "The folder operation failed. No scan was started.",
};
const operationErrors = {
  native_picker_timeout: "Windows did not return a folder selection within two minutes. Try choosing the folder again; no folder was authorized or scanned.",
  native_picker_unavailable: "Windows could not open the folder dialog. Try again; no folder was authorized or scanned.",
};

function savedOperation() {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(LOCAL_FOLDER_STORAGE_KEY));
    return typeof value?.operation_id === "string" ? value : null;
  } catch { return null; }
}

function saveOperation(value) {
  window.sessionStorage.setItem(LOCAL_FOLDER_STORAGE_KEY, JSON.stringify(value));
}

export function hasUncertainScan(rootId) {
  return window.sessionStorage.getItem(recoveryKey(rootId)) === "true";
}

export function clearUncertainScan(rootId) {
  window.sessionStorage.removeItem(recoveryKey(rootId));
}

export function LocalFolderAuthorization({ adapter, localAdapter = bridge, onAccepted, onOpenResults }) {
  const [saved, setSaved] = useState(savedOperation);
  const [operation, setOperation] = useState(null);
  const [connected, setConnected] = useState(false);
  const [readError, setReadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [scanError, setScanError] = useState(null);
  const [posting, setPosting] = useState(false);
  const [cycle, setCycle] = useState(0);
  const [recoveredRoot, setRecoveredRoot] = useState(null);
  const [scanPending, setScanPending] = useState(false);
  const alive = useRef(true);
  const actionPending = useRef(false);
  const readController = useRef(null);
  const scanAttempt = useRef(saved?.scan_attempt || null);
  const scanPosting = useRef(false);
  const operationId = saved?.operation_id;

  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  useEffect(() => {
    const controller = new AbortController();
    readController.current = controller;
    let timer;
    async function poll() {
      try {
        if (!operationId) await localAdapter.getStatus({ signal: controller.signal });
        else {
          const next = await localAdapter.getOperation(operationId, { signal: controller.signal });
          if (!controller.signal.aborted) {
            setOperation(next);
            if (next.state === "cancelled") {
              const current = savedOperation();
              if (current?.operation_id === operationId && !current.scan_attempt) {
                window.sessionStorage.removeItem(LOCAL_FOLDER_STORAGE_KEY);
                setSaved(null);
              }
            }
          }
        }
        if (controller.signal.aborted) return;
        setConnected(true); setReadError(null); setActionError(null);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error?.code === "LOCAL_FOLDER_NOT_FOUND" && !scanAttempt.current) {
          window.sessionStorage.removeItem(LOCAL_FOLDER_STORAGE_KEY);
          setSaved(null); setOperation(null); setConnected(true); setReadError(null);
          return;
        }
        setConnected(error?.code === "LOCAL_FOLDER_NOT_FOUND"); setReadError(error);
      }
      timer = window.setTimeout(poll, 1500);
    }
    poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [localAdapter, operationId, cycle]);

  const submitScan = useCallback(async (attempt) => {
    if (scanPosting.current) return;
    scanPosting.current = true;
    scanAttempt.current = attempt;
    const nextSaved = { operation_id: operationId, scan_attempt: attempt };
    saveOperation(nextSaved); setSaved(nextSaved); setScanPending(true); setScanError(null);
    try {
      const accepted = await adapter.createRootScan(attempt.mount_id, attempt.relative_path);
      if (!alive.current) return;
      window.sessionStorage.removeItem(LOCAL_FOLDER_STORAGE_KEY);
      clearUncertainScan(accepted.root_id);
      window.sessionStorage.setItem("lastRootId", accepted.root_id);
      setSaved(null); setOperation(null); scanAttempt.current = null;
      onAccepted(accepted);
    } catch (error) {
      if (!alive.current) return;
      setScanError(error);
      if (error.status >= 400 && error.status < 500 && error.status !== 409) {
        const rejected = { ...nextSaved, scan_attempt: { ...attempt, rejected: true } };
        saveOperation(rejected); setSaved(rejected); scanAttempt.current = rejected.scan_attempt;
      }
    } finally { scanPosting.current = false; if (alive.current) setScanPending(false); }
  }, [adapter, onAccepted, operationId]);

  useEffect(() => {
    if (operation?.state !== "ready" || scanAttempt.current || !operation.mount_id) return;
    submitScan({ mount_id: operation.mount_id, relative_path: "." });
  }, [operation?.state, operation?.mount_id, submitScan]);

  useEffect(() => {
    if (!saved?.scan_attempt || saved.scan_attempt.rejected || scanPending) return undefined;
    const controller = new AbortController();
    let timer;
    async function recover() {
      try {
        const roots = await adapter.listRoots({ signal: controller.signal });
        if (controller.signal.aborted) return;
        const root = roots.find((item) => item.mount_id === saved.scan_attempt.mount_id && item.relative_path === saved.scan_attempt.relative_path && item.status !== "revoked");
        if (root) {
          window.sessionStorage.setItem(recoveryKey(root.root_id), "true");
          setRecoveredRoot(root);
          return;
        }
      } catch { /* Only reads are retried; the scan request is never replayed. */ }
      timer = window.setTimeout(recover, 2000);
    }
    recover();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [adapter, saved, scanPending, cycle]);

  async function choose() {
    if (actionPending.current || (saved?.scan_attempt && !saved.scan_attempt.rejected) || (operationId && !saved?.scan_attempt?.rejected && !["selected", "cancelled", "failed"].includes(operation?.state))) return;
    const id = crypto.randomUUID();
    const nextSaved = { operation_id: id };
    saveOperation(nextSaved); setSaved(nextSaved);
    scanAttempt.current = null;
    setOperation({ operation_id: id, state: "selecting" });
    setRecoveredRoot(null); setActionError(null); setScanError(null);
    actionPending.current = true; setPosting(true);
    readController.current?.abort();
    try {
      const next = await localAdapter.startSelection(id);
      if (alive.current) setOperation(next);
    } catch (error) { if (alive.current) setActionError(error); }
    finally { actionPending.current = false; if (alive.current) { setPosting(false); setCycle((value) => value + 1); } }
  }

  async function authorize() {
    if (actionPending.current || !["selected", "failed"].includes(operation?.state) || !operation?.display_path || saved?.scan_attempt) return;
    actionPending.current = true; setPosting(true); setActionError(null);
    readController.current?.abort();
    try {
      const next = await localAdapter.prepare(operationId);
      if (alive.current) setOperation(next);
    } catch (error) { if (alive.current) setActionError(error); }
    finally { actionPending.current = false; if (alive.current) { setPosting(false); setCycle((value) => value + 1); } }
  }

  async function resumeSelection() {
    if (actionPending.current || !operationId || saved?.scan_attempt) return;
    actionPending.current = true; setPosting(true); setActionError(null);
    readController.current?.abort();
    try {
      const next = await localAdapter.startSelection(operationId);
      if (alive.current) setOperation(next);
    } catch (error) { if (alive.current) setActionError(error); }
    finally { actionPending.current = false; if (alive.current) { setPosting(false); setCycle((value) => value + 1); } }
  }

  const rejectedScan = Boolean(saved?.scan_attempt?.rejected);
  const uncertain = Boolean(saved?.scan_attempt) && !rejectedScan && !scanPending;
  const busy = posting || scanPending || preparationStates.has(operation?.state) || operation?.state === "selecting";
  const cannotRestoreSelection = readError?.code === "LOCAL_FOLDER_UNAVAILABLE" && operationId && !saved?.scan_attempt;
  const missingSavedSelection = readError?.code === "LOCAL_FOLDER_NOT_FOUND" && operationId && !scanAttempt.current;
  return <section className="workspace-panel glass-card authorization-panel local-folder-panel" aria-label="Local folder authorization">
    <div className="panel-topline"><div><span className="panel-icon"><FolderOpen size={17} /></span><span>YOUR LOCAL FOLDERS</span></div></div>
    <h2>Choose a folder on this computer</h2>
    <p className="panel-intro">Select a Windows folder, then authorize read-only access to its files and subfolders. File Trace reads the originals from that folder.</p>
    {(!operationId || ["cancelled", "failed"].includes(operation?.state)) && <button className="secondary-button" disabled={!connected || posting} onClick={choose}>Choose local folder</button>}
    {operationId && !operation && <p role="status">Restoring your previous folder selection…</p>}
    {operation && <p role="status" aria-live="polite">{messages[operation.state]}</p>}
    {operation?.display_path && <div className="local-folder-selection"><strong>{operation.folder_name}</strong><code>{operation.display_path}</code></div>}
    {operation?.state === "selected" && !uncertain && <>
      <div className="form-hint"><LockKey size={16} /><span>Access stays inside this folder. Original files are never moved, renamed or overwritten.</span></div>
      <button className="primary-button" disabled={!connected || busy} onClick={authorize}>{posting ? "Requesting authorization…" : "Authorize and start scan"}</button>
      <button className="text-button" disabled={busy} onClick={choose}>Choose another folder</button>
    </>}
    {operation?.state === "failed" && operation.display_path && !saved?.scan_attempt && <button className="primary-button" disabled={!connected || posting} onClick={authorize}>Retry preparation</button>}
    {readError?.code === "LOCAL_FOLDER_NOT_FOUND" && !saved?.scan_attempt && <button className="secondary-button" disabled={posting} onClick={resumeSelection}>Resume saved folder selection</button>}
    {scanPending && <p role="status">Requesting your first scan…</p>}
    {uncertain && <div className="notice notice-info" role="status"><div><strong>{recoveredRoot ? "Folder authorization exists. Scan acceptance is unconfirmed." : "Scan acceptance is unconfirmed. Checking saved authorizations…"}</strong><span>This scan request will not be replayed. Current indexed content may still be preparing.</span></div></div>}
    {scanError && <p role="alert">{scanError.message}</p>}
    {rejectedScan && <div className="local-folder-retry"><p>The scan request was refused. You can retry explicitly or choose another folder.</p><button className="primary-button" disabled={scanPending} onClick={() => submitScan({ mount_id: saved.scan_attempt.mount_id, relative_path: saved.scan_attempt.relative_path })}>Retry scan request</button><button className="text-button" disabled={scanPending} onClick={choose}>Choose another folder</button></div>}
    {recoveredRoot && <button className="secondary-button" onClick={() => { window.sessionStorage.removeItem(LOCAL_FOLDER_STORAGE_KEY); onOpenResults(recoveredRoot.root_id); }}>View current indexed content</button>}
    {(readError || actionError) && <div className="notice notice-danger" role="alert"><div><strong>{cannotRestoreSelection ? "Cannot check the previous folder selection because the local folder service is unavailable." : (readError || actionError).message}</strong><span>{cannotRestoreSelection ? <>Cancelling the picker does not grant access or start a scan. Restart the project with <code>python scripts/start.py</code>, then refresh to check the saved result.</> : missingSavedSelection ? "The local service is responding, but the saved operation record is missing. Resume the selection to reopen the folder picker. No folder has been authorized or scanned." : <>Start the local folder service with <code>python scripts/start.py</code>. Check Windows and browser permission if access is blocked.</>}</span></div></div>}
    {operation?.state === "failed" && operation.error_code && <p role="alert">{operationErrors[operation.error_code] || `Error code: ${operation.error_code}`}</p>}
    {(readError || actionError || uncertain) && <button className="text-button" onClick={() => setCycle((value) => value + 1)}>Refresh connection and authorization reads</button>}
  </section>;
}
