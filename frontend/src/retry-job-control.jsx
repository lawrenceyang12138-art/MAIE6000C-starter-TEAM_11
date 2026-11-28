import { useEffect, useRef, useState } from "react";

export function RetryJobControl({ adapter, job, statusVersion, onAccepted, onRefresh }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [locked, setLocked] = useState(false);
  const posting = useRef(false);
  const previousStatusVersion = useRef(statusVersion);

  useEffect(() => {
    if (previousStatusVersion.current !== statusVersion) {
      previousStatusVersion.current = statusVersion;
      setLocked(false);
    }
  }, [statusVersion]);

  if (job?.status !== "failed") return null;

  async function retry() {
    if (posting.current || locked) return;
    posting.current = true;
    setPending(true);
    setError(null);
    try {
      const accepted = await adapter.retryJob(job.job_id, job.root_id);
      setLocked(true);
      onAccepted(accepted);
    } catch (caught) {
      setError(caught);
      setLocked(true);
      onRefresh();
    } finally {
      posting.current = false;
      setPending(false);
    }
  }

  return <section className="rescan-control" aria-label="Retry failed scan job">
    <button className="secondary-button" disabled={pending || locked} onClick={retry}>
      {pending ? "Requesting retry…" : "Retry failed job"}
    </button>
    {error && <div className="notice notice-danger" role="alert"><div><strong>{error.message}</strong><span>{error.code} · {locked ? "Refreshing the latest Job status before another retry." : "Latest Job status refreshed; submit again only if it is still failed."}</span></div></div>}
    {locked && !error && <p role="status">Retry was accepted. The same job is queued; processing is not yet complete.</p>}
    {locked && error && <p role="status">The retry response was not accepted. No request was replayed; waiting for a fresh job read.</p>}
    {!locked && error && <p role="status">The latest job read is still failed. Another retry requires a new user action.</p>}
  </section>;
}
