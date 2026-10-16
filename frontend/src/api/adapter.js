import mockData from "../mock/data.json" with { type: "json" };
import { AdapterError } from "./errors.js";
import { createMockAdapter } from "./mock-adapter.js";
import { createApiAdapter } from "./http-adapter.js";

export { AdapterError, createMockAdapter, createApiAdapter };

// API failures never switch to demonstration data. Mock mode is an explicit choice.
export function createAdapter({
  mode = import.meta.env?.VITE_DATA_MODE || "api",
  baseUrl = import.meta.env?.VITE_API_BASE_URL || "/api",
} = {}) {
  if (!["api", "mock"].includes(mode)) throw new Error("VITE_DATA_MODE must be api or mock.");
  return mode === "api"
    ? createApiAdapter({ baseUrl })
    : createMockAdapter(mockData);
}
