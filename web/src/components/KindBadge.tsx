import type { NodeKind } from "../api/types";
import { KIND_COLORS } from "../theme";

export default function KindBadge({ kind }: { kind: NodeKind }) {
  return (
    <span className="kind-badge" style={{ background: KIND_COLORS[kind] }}>
      {kind}
    </span>
  );
}
