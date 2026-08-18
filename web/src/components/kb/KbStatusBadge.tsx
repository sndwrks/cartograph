import type { KbStatus } from "../../api/types";
import { Badge, type BadgeVariant } from "../../ui";

/**
 * Variants are chosen by the colour they RENDER, not by their name:
 * Badge.module.css maps `.warning` to --color-warn (red) and `.danger` to
 * --color-caution (yellow), which is inverted relative to the tokens. Fixing
 * that would silently recolour every existing consumer, so it is left alone.
 */
const VARIANTS: Record<KbStatus, BadgeVariant> = {
  published: "success", // green
  proposed: "danger", // yellow — awaiting a human
  rejected: "warning", // red
  archived: "default",
};

export default function KbStatusBadge({ status }: { status: KbStatus }) {
  return <Badge variant={VARIANTS[status] ?? "default"}>{status}</Badge>;
}
