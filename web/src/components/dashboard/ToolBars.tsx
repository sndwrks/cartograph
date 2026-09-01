import type { UsageToolRow } from "../../api/types";
import { formatCompact, formatDuration } from "../../format";
import { cx } from "../../ui";
import styles from "./dashboard.module.css";

export default function ToolBars({
  rows,
  selected,
  onSelect,
}: {
  rows: UsageToolRow[];
  selected: string | null;
  onSelect: (tool: string | null) => void;
}) {
  const sorted = [...rows].sort((a, b) => b.calls - a.calls);
  const max = sorted[0]?.calls ?? 0;
  return (
    <section className={styles.card}>
      <h2 className={styles.sectionHeading}>Calls by tool</h2>
      {sorted.length === 0 ? (
        <p className={styles.empty}>No calls in this window.</p>
      ) : (
        <ul className={styles.barList}>
          {sorted.map((row) => (
            <li key={row.tool}>
              {/* a row is also the CallsTable filter — click again to clear */}
              <button
                type="button"
                className={cx(styles.barRow, selected === row.tool && styles.barRowActive)}
                onClick={() => onSelect(selected === row.tool ? null : row.tool)}
              >
                <span className={styles.barName}>{row.tool}</span>
                <span className={styles.barStats}>
                  {formatCompact(row.calls)} calls · {formatDuration(row.p50_duration_ms)} p50
                  {row.errors > 0 && ` · ${formatCompact(row.errors)} err`}
                </span>
                <span className={styles.meter}>
                  <span
                    className={styles.meterFill}
                    style={{ width: `${max > 0 ? (row.calls / max) * 100 : 0}%` }}
                  />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
