// Visual conventions — the single source of truth every slice imports.

import type { Confidence, NodeKind } from "./api/types";

export const KIND_COLORS: Record<NodeKind, string> = {
  module: "#7aa2f7",
  class: "#e0af68",
  function: "#9ece6a",
  method: "#73daca",
  file: "#565f89",
  doc: "#bb9af7",
  config: "#f7768e",
};

// Canvas line-dash patterns: resolved solid, llm_inferred dashed, name_match dotted.
export const CONFIDENCE_LINE_STYLE: Record<Confidence, number[]> = {
  resolved: [],
  llm_inferred: [6, 3],
  name_match: [2, 3],
};

// Badge/pill colors matching the line-style semantics.
export const CONFIDENCE_COLORS: Record<Confidence, string> = {
  resolved: "#9ece6a",
  llm_inferred: "#e0af68",
  name_match: "#787c99",
};

export const COMMUNITY_COLOR = "#7aa2f7";
export const EDGE_COLOR = "#3b4261";
export const LABEL_COLOR = "#c0caf5";
export const BACKGROUND_COLOR = "#16161e";
