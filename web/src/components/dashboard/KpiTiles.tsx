import type { UsageTotals } from "../../api/types";
import { formatCompact, formatPercent, formatTokens } from "../../format";
import { cx } from "../../ui";
import styles from "./dashboard.module.css";

function Tile({
  label,
  value,
  hint,
  warn,
}: {
  label: string;
  value: string;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div className={cx(styles.tile, warn && styles.tileWarn)}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileValue}>{value}</span>
      {hint && <span className={styles.tileHint}>{hint}</span>}
    </div>
  );
}

export default function KpiTiles({ totals }: { totals: UsageTotals }) {
  const hasBaseline = totals.baseline_calls > 0;
  return (
    <div className={styles.tiles}>
      <Tile
        label="Tool calls"
        value={formatCompact(totals.calls)}
        hint={
          totals.unscoped_calls > 0
            ? `${formatCompact(totals.unscoped_calls)} named no repo`
            : undefined
        }
      />
      <Tile
        label="Errors"
        value={formatCompact(totals.errors)}
        warn={totals.errors > 0}
      />
      <Tile label="Tokens returned" value={formatTokens(totals.est_tokens_returned)} />
      <Tile
        label="Tokens saved"
        value={hasBaseline ? formatTokens(totals.est_tokens_saved) : "—"}
        hint={hasBaseline ? `vs ${formatTokens(totals.est_tokens_baseline)} reading files` : "no graph calls yet"}
      />
      <Tile
        label="Saved"
        value={formatPercent(totals.savings_ratio)}
        hint={hasBaseline ? `over ${formatCompact(totals.baseline_calls)} graph calls` : undefined}
      />
      <Tile
        label="File reads avoided"
        value={hasBaseline ? formatCompact(totals.baseline_files) : "—"}
      />
      <Tile label="Agents" value={formatCompact(totals.agents)} />
    </div>
  );
}
