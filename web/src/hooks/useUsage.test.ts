import { describe, expect, it } from "vitest";

import { fillBuckets, parseWindow } from "./useUsage";

describe("parseWindow", () => {
  it("accepts the known windows and defaults the rest", () => {
    expect(parseWindow("24h")).toBe("24h");
    expect(parseWindow("all")).toBe("all");
    expect(parseWindow(null)).toBe("7d");
    expect(parseWindow("garbage")).toBe("7d");
  });
});

describe("fillBuckets", () => {
  const now = Date.UTC(2026, 0, 10, 15, 30); // 15:30Z on Jan 10
  const row = (start: string, calls: number) => ({
    start,
    calls,
    errors: 0,
    response_bytes: calls * 10,
    baseline_bytes: calls * 40,
    baseline_response_bytes: calls * 10,
  });

  it("fills 8 days ending today (the oldest partial one included), keeping provided rows", () => {
    // a 7d window at 15:30Z on Jan 10 starts 15:30Z on Jan 3, so Jan 3 is a
    // real (partial) bucket the server can return — it must keep its slot
    const rows = [row("2026-01-08T00:00:00.000Z", 3), row("2026-01-03T00:00:00.000Z", 1)];
    const out = fillBuckets(rows, "7d", now);
    expect(out).toHaveLength(8);
    expect(out[0]).toEqual(rows[1]);
    expect(out[7].start).toBe("2026-01-10T00:00:00.000Z");
    expect(out[5]).toEqual(rows[0]);
    expect(out.filter((r) => r.calls === 0)).toHaveLength(6);
    expect(out[1].baseline_response_bytes).toBe(0);
  });

  it("fills 25 hourly buckets for the 24h window", () => {
    const out = fillBuckets([], "24h", now);
    expect(out).toHaveLength(25);
    expect(out[24].start).toBe("2026-01-10T15:00:00.000Z");
    expect(out[0].start).toBe("2026-01-09T15:00:00.000Z");
  });

  it("fills 31 days for 30d", () => {
    expect(fillBuckets([], "30d", now)).toHaveLength(31);
  });

  it("leaves 'all' untouched", () => {
    const rows = [row("2025-06-01T00:00:00.000Z", 1)];
    expect(fillBuckets(rows, "all", now)).toBe(rows);
  });
});
