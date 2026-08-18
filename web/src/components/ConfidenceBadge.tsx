import type { Confidence } from "../api/types";
import styles from "./ConfidenceBadge.module.css";

export default function ConfidenceBadge({
  confidence,
}: {
  confidence: Confidence;
}) {
  return (
    <span
      className={styles.badge}
      data-confidence={confidence}
      title={
        confidence === "resolved"
          ? "Proven by imports/analysis"
          : confidence === "llm_inferred"
            ? "Model judgment"
            : "Unproven name match"
      }
    >
      {confidence}
    </span>
  );
}
