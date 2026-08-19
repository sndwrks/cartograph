/**
 * App-level inline SVG icons.
 *
 * Separate from `src/ui/glyphs.tsx`, which the kit keeps internal for its own
 * primitive indicators (chevrons, check, close inside Dialog/Select). These are
 * content icons the app renders itself.
 *
 * They are SVG rather than text characters (⚙, ✕) on purpose: a glyph's ink sits
 * wherever the font puts it inside its em box — ⚙ paints entirely above the
 * baseline — so a flex-centred text character lands visibly low even when every
 * box centre lines up, and the amount varies by platform font. An SVG's artwork
 * is symmetric about its own viewBox, so centring is exact and identical
 * everywhere. Sized in `em` and stroked with `currentColor` so font-size and
 * color drive them, matching the kit's glyph convention.
 */
import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  width: "1em",
  height: "1em",
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
};

export function Gear(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} viewBox="0 0 24 24" strokeWidth={1.75} {...props}>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function Ellipsis(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} viewBox="0 0 16 16" fill="currentColor" stroke="none" {...props}>
      <circle cx="3" cy="8" r="1.5" />
      <circle cx="8" cy="8" r="1.5" />
      <circle cx="13" cy="8" r="1.5" />
    </svg>
  );
}

export function Close(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} viewBox="0 0 16 16" strokeWidth={1.5} {...props}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}
