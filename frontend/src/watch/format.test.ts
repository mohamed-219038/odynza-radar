import { describe, expect, it } from "vitest";
import { ago, cleanLogos, fieldLabel, planName, rights, tabOpen, toCsv, watchSteps } from "./format";

describe("watch helpers", () => {
  it("rights follow the watch router roles", () => {
    expect(rights("client")).toEqual({ decide: true, staff: false });
    expect(rights("viewer")).toEqual({ decide: false, staff: false });
    expect(rights("member")).toEqual({ decide: true, staff: true });
  });
  it("relative times", () => {
    const now = Date.parse("2026-10-15T12:00:00Z");
    expect(ago("2026-10-15T10:00:00", now)).toBe("2h ago");
    expect(ago("2026-10-18T12:00:00Z", now)).toBe("in 3d");
    expect(ago(null, now)).toBe("never");
  });
  it("labels and CSV", () => {
    expect(fieldLabel("price:Business")).toBe("Price · Business");
    expect(toCsv([["a,b", 'say "hi"', null]])).toBe('"a,b","say ""hi""",""');
  });
  it("tabs open step by step", () => {
    const none = watchSteps(false);
    expect(tabOpen("setup", none)).toBe(true);
    expect(tabOpen("competitors", none)).toBe(false);
    const p = { confirmed: 1, captures: 0, collections: 0, running: null, scoring: 0, changes: 0, signals: 0, briefs: 0, opportunities: 0 };
    const picked = watchSteps(true, p);
    expect(tabOpen("sources", picked)).toBe(true);
    expect(tabOpen("overview", picked)).toBe(false);
    const collected = watchSteps(true, { ...p, captures: 20 });
    expect(tabOpen("compare", collected)).toBe(true);
    expect(tabOpen("opportunities", collected)).toBe(false);
    expect(tabOpen("opportunities", watchSteps(true, { ...p, captures: 20, briefs: 1 }))).toBe(true);
  });
  it("client logos and unnamed plans", () => {
    expect(cleanLogos(["Logo for Botpress Certified Partner", "Photo of Cameron Lile", "Kia brand logo in a stylized black modern font.", "KIA", "MTN"], "Botpress")).toEqual(["Kia", "MTN"]);
    expect(planName("price 2")).toBe("Unnamed plan");
    expect(planName("Business")).toBe("Business");
  });
});
