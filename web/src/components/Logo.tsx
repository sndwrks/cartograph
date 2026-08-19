/**
 * The Cartograph brand mark: a small graph — one hub, five satellites.
 *
 * Kept out of `icons.tsx` — that file is documented as app-level *content*
 * icons (Gear, Close), and a brand mark is not one. It does follow the same
 * conventions: sized in `em` and drawn with `currentColor` so font-size and
 * color drive it, which is why TopBar needs no color rule of its own — the
 * mark inherits the wordmark's `--color-accent-text`.
 *
 * ── Construction ───────────────────────────────────────────────────────────
 * Edges are plain lines drawn hub-center to satellite-center, then the nodes
 * are painted over them as *filled* circles — the fill covers the line ends,
 * so no trim-to-circumference math is needed and the geometry stays four
 * numbers per edge. Draw order (edges first) is therefore load-bearing.
 *
 * The satellites vary in size and sit at irregular angles so the star reads
 * as a graph neighborhood — a node and its weighted neighbors — rather than
 * as an asterisk or an atom.
 *
 * `favicon.svg` carries the same construction with one satellite dropped and
 * everything thickened for 16px. Keep the two in sync.
 */
import type { SVGProps } from "react";

/**
 * `aria-hidden` because every current caller sits next to the visible word
 * "Cartograph"; the mark is decorative there and must not be announced twice.
 * A caller using it *without* an adjacent text label should override with
 * `role="img"` and an `aria-label`.
 */
export function GraphMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="1em"
      height="1em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
      {...props}
    >
      {/* Spokes, hub (11.5, 12) out to each satellite. */}
      <path d="M11.5 12L4.5 5M11.5 12L18 4.5M11.5 12L20.5 14.5M11.5 12L6 19.5M11.5 12L14.5 20.5" />
      {/* Nodes, filled so they seat over the edge endpoints. Hub first. */}
      <g fill="currentColor" stroke="none">
        <circle cx="11.5" cy="12" r="2.5" />
        <circle cx="4.5" cy="5" r="2.2" />
        <circle cx="18" cy="4.5" r="1.7" />
        <circle cx="20.5" cy="14.5" r="2" />
        <circle cx="6" cy="19.5" r="1.6" />
        <circle cx="14.5" cy="20.5" r="1.9" />
      </g>
    </svg>
  );
}
