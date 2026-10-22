import { useEffect, useRef, useState } from "react";

export function RescanControl({ adapter, rootId, onAccepted }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [locked, setLocked] = useState(false);
  const posting = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  async function rescan() {
    if (posting.current || locked) return;
    posting.current = true;
    setPending(true); setError(null);
    try {
      const accepted = await adapter.rescanRoot(rootId);
      if (alive.current) {
        setLocked(true);
        onAccepted(accepted);
      }
    } catch (caught) {
      if (alive.current) {
        setError(caught);
        // An uncertain response may follow an accepted POST. Never replay it.
        setLocked(["REQUEST_TIMEOUT", "NETWORK_ERROR", "CONTRACT_MISMATCH"].includes(caught.code) || caught.status >= 500);
      }
    } finally {
      posting.current = false;
      if (alive.current) setPending(false);
    }
  }

  return <section className="rescan-control" aria-label="Scan this directory again">
    <button className="secondary-button" disabled={pending || locked} onClick={rescan}>{pending ? "Requesting scan…" : "Rescan directory"}</button>
    <p>Queue a new scan of this authorized directory. Existing results remain available.</p>
    {error && <div className="notice notice-danger" role="alert"><div><strong>{error.message}</strong><span>{error.code}</span></div></div>}
    {error && locked && <p role="status">Scan acceptance is uncertain. Check directory jobs before submitting again; this request will not be replayed automatically.</p>}
  </section>;
}
