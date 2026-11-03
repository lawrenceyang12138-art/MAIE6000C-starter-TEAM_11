import { useCallback, useEffect, useRef, useState } from "react";

const slowStates = new Set(["ready", "error", "disabled", "unavailable"]);

// One request at a time. Navigation/unmount and retry both invalidate late reads.
export function useSetup(adapter) {
  const [status, setStatus] = useState(null);
  const [readError, setReadError] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [cycle, setCycle] = useState(0);
  const generation = useRef(0);
  const pollController = useRef(null);
  const retryController = useRef(null);
  const timer = useRef(null);
  const posting = useRef(null);
  const lastAdapter = useRef(adapter);

  useEffect(() => {
    posting.current = null;
    retryController.current = null;
    setRetrying(false);
    if (lastAdapter.current !== adapter) {
      lastAdapter.current = adapter;
      setStatus(null);
      setReadError(false);
    }
    if (adapter.mode === "mock") return undefined;
    const current = ++generation.current;
    const controller = new AbortController();
    pollController.current = controller;
    async function poll() {
      let delay = 10000;
      try {
        const next = await adapter.getSetup({ signal: controller.signal });
        if (controller.signal.aborted || generation.current !== current) return;
        setStatus(next);
        setReadError(false);
        delay = slowStates.has(next.state) ? 10000 : 1000;
      } catch {
        if (controller.signal.aborted || generation.current !== current) return;
        // Cached readiness must not remain green after the status service is lost.
        setStatus(null);
        setReadError(true);
      }
      timer.current = window.setTimeout(poll, delay);
    }
    poll();
    return () => {
      generation.current += 1;
      controller.abort();
      retryController.current?.abort();
      window.clearTimeout(timer.current);
    };
  }, [adapter, cycle]);

  const retry = useCallback(async () => {
    if (posting.current || adapter.mode === "mock") return;
    const current = ++generation.current;
    pollController.current?.abort();
    window.clearTimeout(timer.current);
    const controller = new AbortController();
    posting.current = controller;
    retryController.current = controller;
    setRetrying(true);
    setReadError(false);
    try {
      const next = await adapter.retrySetup({ signal: controller.signal });
      if (!controller.signal.aborted && generation.current === current) setStatus(next);
    } catch {
      if (!controller.signal.aborted && generation.current === current) {
        setStatus(null);
        setReadError(true);
      }
    } finally {
      if (posting.current === controller) posting.current = null;
      if (!controller.signal.aborted && generation.current === current) {
        setRetrying(false);
        // Resume reads even if a POST timed out: do not automatically replay it.
        setCycle((value) => value + 1);
      }
    }
  }, [adapter]);

  return { status, readError, retrying, retry };
}
