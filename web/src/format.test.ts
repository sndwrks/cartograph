import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCompact,
  formatDuration,
  formatPercent,
  formatTokens,
  relativeTime,
} from "./format";

describe("formatCompact", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, "1k"],
    [1200, "1.2k"],
    [12_345, "12k"],
    [999_999, "1000k"],
    [1e6, "1M"],
    [1.5e6, "1.5M"],
    [2.1e9, "2.1B"],
    [-1500, "-1.5k"],
  ])("%d → %s", (n, out) => {
    expect(formatCompact(n)).toBe(out);
  });
  it("dashes non-finite input", () => {
    expect(formatCompact(NaN)).toBe("—");
  });
});

describe("formatTokens", () => {
  it("marks the value as an estimate", () => {
    expect(formatTokens(1200)).toBe("≈1.2k");
  });
});

describe("formatBytes", () => {
  it("steps through B / KB / MB", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0 ms"],
    [999, "999 ms"],
    [1000, "1.0 s"],
    [61_000, "1.0 min"],
  ])("%d → %s", (ms, out) => {
    expect(formatDuration(ms)).toBe(out);
  });
});

describe("formatPercent", () => {
  it("rounds and dashes the empty cases", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.4567)).toBe("46%");
    expect(formatPercent(-0.2)).toBe("-20%");
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(NaN)).toBe("—");
  });
});

describe("relativeTime", () => {
  const now = Date.UTC(2026, 0, 2, 12, 0, 0);
  it("buckets by unit with an injected clock", () => {
    expect(relativeTime(new Date(now - 10_000).toISOString(), now)).toBe("just now");
    expect(relativeTime(new Date(now - 5 * 60_000).toISOString(), now)).toBe("5m ago");
    expect(relativeTime(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("3h ago");
    expect(relativeTime(new Date(now - 2 * 86_400_000).toISOString(), now)).toBe("2d ago");
  });
  it("never goes negative for a future timestamp", () => {
    expect(relativeTime(new Date(now + 60_000).toISOString(), now)).toBe("just now");
  });
});
