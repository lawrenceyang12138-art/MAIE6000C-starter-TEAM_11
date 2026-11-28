import { useCallback, useEffect, useRef, useState } from "react";
import { AdapterError } from "../api/errors.js";
import { normalizeQuery } from "./search.js";

export function useSearch(adapter, rootId, refreshToken = 0) {
  const [state, setState] = useState({ status: "idle", response: null, error: null, request: null });
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1;
    setState({ status: "idle", response: null, error: null, request: null });
    return () => { generation.current += 1; };
  }, [rootId, refreshToken]);

  const run = useCallback(async (input) => {
    const requestId = ++generation.current;
    const query = normalizeQuery(input.query);
    const request = { ...input, query, rootId };
    if (!query || query.length > 500) {
      setState({ status: "error", response: null, request, error: new AdapterError(
        "Enter a query of 1 to 500 characters.", { code: "invalid_query", status: 422 }) });
      return;
    }
    setState({ status: "loading", response: null, error: null, request });
    try {
      const response = await adapter.search(request);
      if (generation.current === requestId) setState({ status: "success", response, error: null, request });
    } catch (error) {
      if (generation.current === requestId) setState({ status: "error", response: null, error, request });
    }
  }, [adapter, rootId]);
  const clear = useCallback(() => {
    generation.current += 1;
    setState({ status: "idle", response: null, error: null, request: null });
  }, []);
  return { ...state, run, clear };
}
