// Shared node/edge styling helpers for the community and ego views.

import type { CanvasLink, CanvasNode } from "./components/GraphCanvas";
import type { EdgeOut, NodeOut } from "./api/types";
import { CONFIDENCE_LINE_STYLE, EDGE_COLOR, KIND_COLORS } from "./theme";

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const escapeHtml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function nodeTooltip(node: NodeOut): string {
  const location =
    node.file_path !== null
      ? `${node.file_path}${node.start_line !== null ? `:${node.start_line}` : ""}`
      : "";
  return `<div class="tooltip"><strong>${escapeHtml(node.qualified_name)}</strong><br/><span class="muted">${node.kind}${
    location ? ` · ${escapeHtml(location)}` : ""
  }</span></div>`;
}

/** Pagerank-proportional radius, scaled relative to the rendered set. */
export function radiusScale(nodes: NodeOut[]): (node: NodeOut) => number {
  const maxRank = Math.max(...nodes.map((node) => node.pagerank), 1e-9);
  return (node) => clamp(5 + 14 * Math.sqrt(node.pagerank / maxRank), 5, 20);
}

export function toCanvasNode(
  node: NodeOut,
  radius: number,
  extras?: Partial<CanvasNode>,
): CanvasNode {
  return {
    id: node.id,
    label: node.name,
    color: KIND_COLORS[node.kind] ?? EDGE_COLOR,
    radius,
    tooltip: nodeTooltip(node),
    ...extras,
  };
}

export function toCanvasLink(edge: EdgeOut): CanvasLink {
  return {
    source: edge.src_id,
    target: edge.dst_id,
    color: `${EDGE_COLOR}dd`,
    width: 1.5,
    dash: CONFIDENCE_LINE_STYLE[edge.confidence],
  };
}

/** Subtle per-community halo color, stable per id. */
export function communityHalo(communityId: number | null): string | undefined {
  if (communityId === null) return undefined;
  return `hsl(${(communityId * 67) % 360} 65% 55% / 0.18)`;
}
