// Visual conventions — the single source of truth every slice imports.
//
// Colors are resolved once at module init from the CSS custom properties
// defined in the "Graph canvas" block of src/styles/tokens.css. The canvas
// (react-force-graph-2d) paints to <canvas>, which cannot read CSS, so this
// module is the bridge. The app is dark-only (<html data-theme="dark"> is
// hardcoded) — there is no theme flip to observe here, so this resolves once
// and never re-reads.

import type { Confidence, NodeKind } from "./api/types";

const root = typeof document !== "undefined" ? document.documentElement : null;
const computed = root ? getComputedStyle(root) : null;

const HEX6 = /^#[0-9a-f]{6}$/i;

/** Graph colors must be 6-digit hex: callers append alpha as a hex suffix
 *  (`${EDGE_COLOR}dd`), which fails silently on any other notation. */
function token(name: string, fallback: string): string {
  const value = computed?.getPropertyValue(name).trim();
  if (value && HEX6.test(value)) return value;
  if (value && import.meta.env.DEV) {
    console.warn(`[theme] ${name} is not 6-digit hex ("${value}") — using ${fallback}`);
  }
  return fallback;
}

export const KIND_COLORS: Record<NodeKind, string> = {
  module: token("--graph-kind-module", "#3987e5"),
  class: token("--graph-kind-class", "#eda100"),
  function: token("--graph-kind-function", "#c2f280"),
  method: token("--graph-kind-method", "#17b8b8"),
  file: token("--graph-kind-file", "#8c8590"),
  doc: token("--graph-kind-doc", "#a78bfa"),
  config: token("--graph-kind-config", "#d92d31"),
};

// Canvas line-dash patterns: resolved solid, llm_inferred dashed, name_match dotted.
export const CONFIDENCE_LINE_STYLE: Record<Confidence, number[]> = {
  resolved: [],
  llm_inferred: [6, 3],
  name_match: [2, 3],
};

// Badge/pill colors matching the line-style semantics.
export const CONFIDENCE_COLORS: Record<Confidence, string> = {
  resolved: token("--graph-confidence-resolved", "#90be6d"),
  llm_inferred: token("--graph-confidence-llm", "#f9c74f"),
  name_match: token("--graph-confidence-name", "#8c8590"),
};

export const COMMUNITY_COLOR = token("--graph-community", "#8b5cf6");
export const EDGE_COLOR = token("--graph-edge", "#49444d");
export const LABEL_COLOR = token("--graph-label", "#e9e4ed");
export const BACKGROUND_COLOR = token("--graph-bg", "#151018");
export const RING_COLOR = token("--graph-ring", "#e9e4ed");
