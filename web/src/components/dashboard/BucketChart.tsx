import type { UsageBucketRow } from "../../api/types";
import { formatCompact, formatTokens } from "../../format";
import styles from "./dashboard.module.css";

function bucketLabel(iso: string, byHour: boolean): string {
  const d = new Date(iso);
  if (byHour) return `${String(d.getUTCHours()).padStart(2, "0")}:00`;
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
}

/**
 * Paired columns per bucket: what an agent would have read (baseline) next
 * to what the tool returned. Same axis, same unit — the gap between the two
 * IS the saving, so the reader sees it without a second scale. Rendered as
 * CSS grid columns rather than SVG: no library, and the tokens do the styling.
 */
export default function BucketChart({
  rows,
  byHour,
  charsPerToken,
}: {
  rows: UsageBucketRow[];
  byHour: boolean;
  charsPerToken: number;
}) {
  // Same rows on both sides: `baseline_response_bytes` is what the baselined
  // calls returned, so a kb/board-heavy day doesn't read as the tools losing.
  const max = Math.max(
    1,
    ...rows.map((r) => Math.max(r.baseline_bytes, r.baseline_response_bytes)),
  );
  // label every Nth slot so 30 days / 24 hours don't collide
  const every = rows.length > 12 ? Math.ceil(rows.length / 8) : 1;
  return (
    <section className={styles.card}>
      <h2 className={styles.sectionHeading}>
        Tokens by {byHour ? "hour" : "day"} — returned vs. reading files (graph tools)
      </h2>
      <div className={styles.chart}>
        {rows.map((r) => (
          <div key={r.start} className={styles.bucket}>
            {r.errors > 0 && <span className={styles.bucketErr} aria-hidden />}
            <span
              className={`${styles.bar} ${styles.barBaseline}`}
              style={{ height: `${(r.baseline_bytes / max) * 100}%` }}
            />
            <span
              className={`${styles.bar} ${styles.barReturned}`}
              style={{ height: `${(r.baseline_response_bytes / max) * 100}%` }}
            />
            <span className={styles.tip} role="tooltip">
              {bucketLabel(r.start, byHour)} · {formatCompact(r.calls)} calls
              {r.errors > 0 && ` · ${r.errors} err`} · returned{" "}
              {formatTokens(r.baseline_response_bytes / charsPerToken)} · files{" "}
              {formatTokens(r.baseline_bytes / charsPerToken)}
              {r.response_bytes !== r.baseline_response_bytes &&
                ` · all tools ${formatTokens(r.response_bytes / charsPerToken)}`}
            </span>
          </div>
        ))}
      </div>
      <div className={styles.axis}>
        {rows.map((r, i) => (
          <span key={r.start} className={styles.axisLabel}>
            {i % every === 0 || i === rows.length - 1 ? bucketLabel(r.start, byHour) : ""}
          </span>
        ))}
      </div>
      <div className={styles.legend}>
        <span className={styles.legendItem}>
          <span className={`${styles.swatch} ${styles.barBaseline}`} />
          reading files (baseline)
        </span>
        <span className={styles.legendItem}>
          <span className={`${styles.swatch} ${styles.barReturned}`} />
          returned by tools
        </span>
        <span className={styles.legendItem}>
          <span className={styles.bucketErr} style={{ position: "static", margin: 0 }} />
          errors
        </span>
      </div>
    </section>
  );
}
