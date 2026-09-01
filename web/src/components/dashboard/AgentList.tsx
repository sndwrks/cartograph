import type { UsageAgentRow } from "../../api/types";
import { formatCompact, relativeTime } from "../../format";
import styles from "./dashboard.module.css";

export default function AgentList({ rows }: { rows: UsageAgentRow[] }) {
  return (
    <section className={styles.card}>
      <h2 className={styles.sectionHeading}>Agents</h2>
      {rows.length === 0 ? (
        <p className={styles.empty}>
          No named agents — only post_message and kb_propose carry an agent name,
          unless the client sends an X-Cartograph-Agent header.
        </p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>agent</th>
              <th className={styles.num}>calls</th>
              <th className={styles.num}>errors</th>
              <th>last seen</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name}>
                <td className={styles.mono}>{row.name}</td>
                <td className={styles.num}>{formatCompact(row.calls)}</td>
                <td className={styles.num}>{formatCompact(row.errors)}</td>
                <td className={styles.muted} title={row.last_call}>
                  {relativeTime(row.last_call)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
