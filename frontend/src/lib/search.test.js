import { describe, expect, it } from "vitest";
import { sourceLocator } from "./search.js";

describe("source locators", () => {
  it("keeps a real PDF page number", () => {
    expect(sourceLocator({ page: 7, ordinal: 12 })).toBe("Page 7");
    expect(sourceLocator({ page_number: 3, ordinal: 1 })).toBe("Page 3");
  });

  it("uses the persisted chunk ordinal when a source has no pages", () => {
    expect(sourceLocator({ page: null, ordinal: 4 })).toBe("原文片段 #4");
    expect(sourceLocator({ page_number: null, ordinal: 11 })).toBe("原文片段 #11");
  });

  it("does not invent a page when the locator is malformed", () => {
    expect(sourceLocator({ page: null, ordinal: 0 })).toBe("Source passage");
    expect(sourceLocator({})).toBe("Source passage");
  });
});
