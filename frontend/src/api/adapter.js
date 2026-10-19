import mockData from "../mock/data.json" with { type: "json" };
import relationData from "../mock/relations.json" with { type: "json" };
import { AdapterError } from "./errors.js";
import { createMockAdapter } from "./mock-adapter.js";
import { createApiAdapter } from "./http-adapter.js";

export { AdapterError, createMockAdapter, createApiAdapter };

// API failures never switch to demonstration data. Mock mode is an explicit choice.
export function createAdapter({
  mode = import.meta.env?.VITE_DATA_MODE || "api",
  baseUrl = import.meta.env?.VITE_API_BASE_URL || "/api",
  scenario = import.meta.env?.VITE_MOCK_SCENARIO || "files",
} = {}) {
  if (!["api", "mock"].includes(mode)) throw new Error("VITE_DATA_MODE must be api or mock.");
  if (mode === "mock" && !["files", "relations"].includes(scenario)) {
    throw new Error("VITE_MOCK_SCENARIO must be files or relations.");
  }
  return mode === "api"
    ? createApiAdapter({ baseUrl })
    : createMockAdapter(scenario === "relations" ? relationData : mockData);
}
