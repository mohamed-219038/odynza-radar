import { describe, expect, it } from "vitest";
import { safePath, safeUrl } from "./format";

describe("links stay safe", () => {
  it("allows only http(s) URLs", () => {
    expect(safeUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl("data:text/html,<b>x</b>")).toBe("");
    expect(safeUrl("//evil.example")).toBe("");
    expect(safeUrl(undefined)).toBe("");
  });
  it("keeps API paths same-origin", () => {
    expect(safePath("/watch/briefs/1/view")).toBe("/watch/briefs/1/view");
    expect(safePath("//evil.example/x")).toBe("");
    expect(safePath("https://evil.example")).toBe("");
    expect(safePath("/\\evil.example")).toBe("");
  });
});
