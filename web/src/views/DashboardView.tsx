import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { UsageWindow } from "../api/types";
import AgentList from "../components/dashboard/AgentList";
import BucketChart from "../components/dashboard/BucketChart";
import CallsTable from "../components/dashboard/CallsTable";
import EstimateNote from "../components/dashboard/EstimateNote";
import IngestCard from "../components/dashboard/IngestCard";
import KpiTiles from "../components/dashboard/KpiTiles";
import ToolBars from "../components/dashboard/ToolBars";
import { USAGE_WINDOWS, fillBuckets, parseWindow, useUsageSummary } from "../hooks/useUsage";
import { useAppStore } from "../store";
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui";
import styles from "./DashboardView.module.css";
import viewFrameStyles from "./viewFrame.module.css";

const WINDOW_LABEL: Record<UsageWindow, string> = {
  "24h": "last 24 hours",
  "7d": "last 7 days",
  "30d": "last 30 days",
  all: "all time",
};

/**
 * The per-repo homepage: is the MCP server earning its keep? Every figure
 * here comes from the server's own per-call records plus a modelled
 * "what would the agent have read instead" baseline — see EstimateNote.
 */
export default function DashboardView() {
  const repo = useAppStore((state) => state.repo);
  const [params, setParams] = useSearchParams();
  // The window lives in the URL (like KbView's filters) so a view is
  // linkable; `replace` so flipping it doesn't pile up history entries.
  const usageWindow = parseWindow(params.get("window"));
  const setWindow = (next: UsageWindow) => {
    const copy = new URLSearchParams(params);
    if (next === "7d") copy.delete("window");
    else copy.set("window", next);
    setParams(copy, { replace: true });
  };
  const [tool, setTool] = useState<string | null>(null);

  const summary = useUsageSummary(repo, usageWindow);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <h1 className={styles.title}>Usage</h1>
          <span className={styles.repoName}>{repo}</span>
        </div>
        <label className={styles.filter}>
          window
          <Select value={usageWindow} onValueChange={(value) => setWindow(value as UsageWindow)}>
            <SelectTrigger aria-label="window">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {USAGE_WINDOWS.map((w) => (
                <SelectItem key={w} value={w}>
                  {WINDOW_LABEL[w]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>
      <div className={styles.body}>
        {repo === null || summary.isPending ? (
          <div className={viewFrameStyles.canvasMessage}>Loading…</div>
        ) : summary.isError ? (
          <div className={viewFrameStyles.canvasMessage}>
            Failed to load usage: {String(summary.error)}
          </div>
        ) : summary.data.totals.calls === 0 ? (
          <div className={styles.content}>
            <div className={viewFrameStyles.canvasMessage}>
              {usageWindow === "all" ? (
                <>
                  <p>
                    No tool calls recorded yet — register the MCP server with your agent
                    and calls will appear here.
                  </p>
                  <pre className={styles.emptyPre}>
                    {`claude mcp add cartograph --scope local --transport http http://localhost:8765/mcp \\
  --header "Authorization: Bearer $MCP_BEARER_TOKEN"`}
                  </pre>
                </>
              ) : (
                <>
                  <p>No tool calls in the {WINDOW_LABEL[usageWindow]}.</p>
                  <div className={styles.emptyActions}>
                    <Button variant="ghost" onClick={() => setWindow("all")}>
                      Show all time
                    </Button>
                  </div>
                </>
              )}
            </div>
            {/* ingest can exist before any call does */}
            <IngestCard repo={repo} />
          </div>
        ) : (
          <div className={styles.content}>
            <KpiTiles totals={summary.data.totals} />
            <BucketChart
              rows={fillBuckets(summary.data.buckets, usageWindow)}
              byHour={summary.data.bucket === "hour"}
              charsPerToken={summary.data.chars_per_token}
            />
            <ToolBars rows={summary.data.by_tool} selected={tool} onSelect={setTool} />
            <CallsTable
              repo={repo}
              window={usageWindow}
              tools={summary.data.by_tool}
              tool={tool}
              onToolChange={setTool}
            />
            <div className={styles.sideBySide}>
              <AgentList rows={summary.data.agents} />
              <IngestCard repo={repo} />
            </div>
            <EstimateNote charsPerToken={summary.data.chars_per_token} />
          </div>
        )}
      </div>
    </div>
  );
}
