import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchIngestRuns, fetchUsageCalls, fetchUsageSummary } from "../api/client";
import type { IngestRunOut, UsageBucketRow, UsageWindow } from "../api/types";

export const USAGE_WINDOWS: readonly UsageWindow[] = ["24h", "7d", "30d", "all"];
export const DEFAULT_WINDOW: UsageWindow = "7d";

/** `?window=` → a valid window; anything missing or unknown is the default. */
export function parseWindow(raw: string | null): UsageWindow {
  return (USAGE_WINDOWS as readonly string[]).includes(raw ?? "")
    ? (raw as UsageWindow)
    : DEFAULT_WINDOW;
}

const HOUR = 3_600_000;
const DAY = 86_400_000;

/**
 * The summary skips empty buckets (it's a GROUP BY), but a bar chart must
 * show them as zero or the x-axis lies about elapsed time. "all" has no
 * fixed span, so it is left as the server sent it.
 */
export function fillBuckets(
  rows: UsageBucketRow[],
  window: UsageWindow,
  now: number = Date.now(),
): UsageBucketRow[] {
  if (window === "all") return rows;
  const byHour = window === "24h";
  const step = byHour ? HOUR : DAY;
  // The server keeps rows with started_at >= now - span, which touches
  // count + 1 truncated buckets: the oldest one is partial (only its tail
  // is inside the window) but its calls are in the totals, so it gets a
  // slot rather than being dropped.
  const count = (byHour ? 24 : window === "7d" ? 7 : 30) + 1;
  // Bucket starts are date_trunc'd server-side in UTC; align our grid the
  // same way (UTC hour/day boundaries) so keys line up exactly.
  const current = byHour
    ? Math.floor(now / HOUR) * HOUR
    : Math.floor(now / DAY) * DAY;
  const known = new Map(rows.map((r) => [new Date(r.start).getTime(), r]));
  const out: UsageBucketRow[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const start = current - i * step;
    out.push(
      known.get(start) ?? {
        start: new Date(start).toISOString(),
        calls: 0,
        errors: 0,
        response_bytes: 0,
        baseline_bytes: 0,
        baseline_response_bytes: 0,
      },
    );
  }
  return out;
}

export function useUsageSummary(repo: string | null, window: UsageWindow) {
  return useQuery({
    queryKey: ["usage", "summary", repo, window],
    queryFn: () => fetchUsageSummary(repo as string, window),
    enabled: repo !== null,
    // agents are calling in while you watch; a minute keeps it live without
    // hammering the aggregate queries
    refetchInterval: 60_000,
  });
}

export function useUsageCalls(
  repo: string | null,
  opts?: { tool?: string; limit?: number; window?: UsageWindow },
) {
  const limit = opts?.limit ?? 50;
  const window = opts?.window ?? DEFAULT_WINDOW;
  return useQuery({
    queryKey: ["usage", "calls", repo, opts?.tool ?? null, limit, window],
    queryFn: () => fetchUsageCalls(repo as string, { tool: opts?.tool, limit, window }),
    enabled: repo !== null,
    refetchInterval: 60_000,
  });
}

export function useIngestRuns(repo: string | null, limit = 5) {
  return useQuery({
    queryKey: ["ingest", "runs", repo, limit],
    queryFn: async (): Promise<IngestRunOut[]> => {
      try {
        return (await fetchIngestRuns(repo as string, limit)).runs;
      } catch (error) {
        // an unregistered repo 404s; the card just shows "no runs" then,
        // mirroring how Overview treats the same status
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }
    },
    enabled: repo !== null,
  });
}
