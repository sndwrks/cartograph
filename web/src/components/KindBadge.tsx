import type { NodeKind } from "../api/types";
import styles from "./KindBadge.module.css";

export default function KindBadge({ kind }: { kind: NodeKind }) {
  return (
    <span className={styles.badge} data-kind={kind}>
      {kind}
    </span>
  );
}
