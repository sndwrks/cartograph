// Number/time formatters for the usage dashboard. Pure so vitest runs them
// in node, and so every tile and column formats the same way.

/** 999 → "999", 1200 → "1.2k", 1.5e6 → "1.5M", 2.1e9 → "2.1B". */
export function formatCompact(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  const step = (v: number, unit: string) => {
    // one decimal below 10, none above — "1.2k" reads, "123.4k" is noise
    const rounded = v < 10 ? Math.round(v * 10) / 10 : Math.round(v);
    return `${sign}${rounded}${unit}`;
  };
  if (abs < 1000) return `${sign}${Math.round(abs)}`;
  if (abs < 1e6) return step(abs / 1e3, "k");
  if (abs < 1e9) return step(abs / 1e6, "M");
  return step(abs / 1e9, "B");
}

/** Token counts are estimates everywhere they appear — say so in the glyph. */
export function formatTokens(n: number): string {
  return `≈${formatCompact(n)}`;
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

/** 0.4567 → "46%"; null/NaN → "—". Negative ratios keep their sign. */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
