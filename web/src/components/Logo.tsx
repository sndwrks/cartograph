/**
 * The Cartograph brand mark: a sextant.
 *
 * Kept out of `icons.tsx` — that file is documented as app-level *content*
 * icons (Gear, Close), and a brand mark is not one. It does follow the same
 * conventions: sized in `em` and stroked with `currentColor` so font-size and
 * color drive it, which is why TopBar needs no color rule of its own — the
 * mark inherits the wordmark's `--color-accent-text`.
 *
 * ── Why these parts ────────────────────────────────────────────────────────
 * An earlier pass drew only the frame (arc + two sides + arm) and it read as a
 * traffic cone: apex at top, symmetric sides, shallow curve closing the
 * bottom. What rescues it is the hardware, and specifically the round hardware
 * — a sextant's recognisable silhouette is its *mounted parts*, not its
 * outline. So the mark carries all four:
 *
 *   index mirror   filled circle at the apex, riding the pivot
 *   horizon glass  circle mounted in the left frame side
 *   telescope      stadium poking left, sharing the horizon glass's axis
 *   micrometer drum circle at the foot of the index arm, on the limb
 *
 * Two further anti-cone measures: the whole instrument is rotated −20° so it
 * reads as held rather than standing, and the left frame side is *broken*
 * either side of the horizon glass so that circle sits in the frame instead of
 * bubbling off its edge.
 *
 * ── Geometry ───────────────────────────────────────────────────────────────
 * Derived, not eyeballed. Every point lies on one circle centred on the pivot
 * at (12.4, 3) — outer radius 16.3, inner 13.4, which is the graduated limb's
 * width. A point at angle θ from straight down is
 * (12.4 + r·sinθ, 3 + r·cosθ). The limb spans θ = ±30°, because a sextant *is*
 * one sixth of a circle; the literal 60° arc is what makes the silhouette read
 * as the instrument. The index arm sits at θ = 0 — deliberately, since at
 * θ = 16° it ran near-parallel to the right frame side and the pair closed
 * into a visual sliver.
 *
 * `favicon.svg` carries the same construction with the graduations dropped and
 * the telescope shortened — both turn to mud at 16px. Keep the two in sync.
 */
import type { SVGProps } from "react";

/**
 * `aria-hidden` because every current caller sits next to the visible word
 * "Cartograph"; the mark is decorative there and must not be announced twice.
 * A caller using it *without* an adjacent text label should override with
 * `role="img"` and an `aria-label`.
 */
export function SextantMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="1em"
      height="1em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
      {...props}
    >
      <g transform="rotate(-20 12 12)">
        {/* Limb: the graduated arc, drawn as a closed band (outer r=16.3,
            inner r=13.4). Sweep-flag 0 on the outer arc bulges it away from
            the pivot; 1 on the inner arc returns along the same side. */}
        <path d="M4.25 17.12A16.3 16.3 0 0 0 20.55 17.12L19.1 14.6A13.4 13.4 0 0 1 5.7 14.6Z" />
        {/* Graduations, radial across the band at θ = −22°, −11°, 0°, 11°, 22°. */}
        <path d="M7.38 15.42L6.29 18.11M9.84 16.15L9.29 19M12.4 16.4L12.4 19.3M14.96 16.15L15.51 19M17.42 15.42L18.51 18.11" />
        {/* Left frame side, broken to seat the horizon glass. */}
        <path d="M12.4 3L9.1 8.72M7.1 12.18L4.25 17.12" />
        {/* Right frame side. */}
        <path d="M12.4 3L20.55 17.12" />
        {/* Index arm, pivot down to the drum it carries. */}
        <path d="M12.4 3L12.4 19" />
        <circle cx="12.4" cy="21" r="2" />
        {/* Horizon glass, and the telescope sighting through it. The stadium's
            right edge is tangent to the circle so they join rather than
            overlap into a lens. */}
        <circle cx="8.1" cy="10.45" r="2" />
        <rect x="1.6" y="8.85" width="4.5" height="3.2" rx="1.6" />
        {/* Index mirror. Filled, so it also covers the joint where the two
            frame sides and the index arm converge on the pivot. */}
        <circle cx="12.4" cy="3" r="1.75" fill="currentColor" stroke="none" />
      </g>
    </svg>
  );
}
