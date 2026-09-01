import { useState } from "react";

import type { UsageCallOut, UsageToolRow, UsageWindow } from "../../api/types";
import { formatBytes, formatDuration, relativeTime } from "../../format";
import { useUsageCalls } from "../../hooks/useUsage";
import {
  Badge,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cx,
} from "../../ui";
import styles from "./dashboard.module.css";

// Radix Select.Item rejects an empty-string value (reserved to mean "no
// selection"), so "all tools" round-trips through this sentinel — same
// precedent as BoardView's agent filter.
const ANY_TOOL = "any";

function CallRow({ call }: { call: UsageCallOut }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className={cx(styles.rowButton, open && styles.rowExpanded)}
        onClick={() => setOpen((v) => !v)}
      >
        <td className={styles.mono}>{call.tool}</td>
        <td className={styles.muted}>{call.agent_name ?? "—"}</td>
        <td className={styles.muted} title={call.started_at}>
          {relativeTime(call.started_at)}
        </td>
        <td className={styles.num}>{formatDuration(call.duration_ms)}</td>
        <td className={styles.num}>
          {formatBytes(call.response_bytes)}
          {call.baseline_bytes !== null && (
            <span className={styles.muted}> / {formatBytes(call.baseline_bytes)}</span>
          )}
        </td>
        <td>
          {call.ok ? (
            <Badge variant="success">ok</Badge>
          ) : (
            <Badge variant="danger" title={call.error ?? undefined}>
              {call.error_kind ?? "error"}
            </Badge>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6} className={styles.detailCell}>
            <pre className={styles.detail}>
              {JSON.stringify(
                { arguments: call.arguments, result_meta: call.result_meta, error: call.error },
                null,
                2,
              )}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

export default function CallsTable({
  repo,
  tools,
  tool,
  onToolChange,
  window,
}: {
  repo: string;
  window: UsageWindow;
  tools: UsageToolRow[];
  tool: string | null;
  onToolChange: (tool: string | null) => void;
}) {
  // same window as the summary above it, so the table and the tiles agree
  const calls = useUsageCalls(repo, { tool: tool ?? undefined, limit: 50, window });
  const rows = calls.data?.calls ?? [];
  return (
    <section className={styles.card}>
      <div className={styles.headingRow}>
        <h2 className={styles.sectionHeading}>Recent calls</h2>
        <label className={styles.filter}>
          tool
          <Select
            value={tool ?? ANY_TOOL}
            onValueChange={(value) => onToolChange(value === ANY_TOOL ? null : value)}
          >
            <SelectTrigger aria-label="tool">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY_TOOL}>all tools</SelectItem>
              {tools.map((t) => (
                <SelectItem key={t.tool} value={t.tool}>
                  {t.tool}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>
      {calls.isPending ? (
        <p className={styles.empty}>Loading…</p>
      ) : calls.isError ? (
        <p className={styles.empty}>Failed to load calls: {String(calls.error)}</p>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>No calls recorded.</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>tool</th>
                <th>agent</th>
                <th>when</th>
                <th className={styles.num}>duration</th>
                <th className={styles.num}>returned / files</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((call) => (
                <CallRow key={call.id} call={call} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
