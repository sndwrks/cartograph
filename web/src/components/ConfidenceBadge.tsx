import type { Confidence } from "../api/types";
import { CONFIDENCE_COLORS } from "../theme";

export default function ConfidenceBadge({
  confidence,
}: {
  confidence: Confidence;
}) {
  return (
    <span
      className="confidence-badge"
      style={{
        color: CONFIDENCE_COLORS[confidence],
        borderColor: CONFIDENCE_COLORS[confidence],
        borderStyle:
          confidence === "resolved"
            ? "solid"
            : confidence === "llm_inferred"
              ? "dashed"
              : "dotted",
      }}
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
