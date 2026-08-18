/**
 * Internal inline SVG glyphs for primitive indicators (chevrons, check, close).
 *
 * Deliberately NOT FontAwesome: the kit stays dependency-free and these glyphs
 * inherit `currentColor` + `1em` sizing so they match surrounding text. The
 * app-level FontAwesome Sharp `Icon` registry (for nav/content icons) is a
 * separate concern. Sharp, 1.5px strokes to match the minimal aesthetic.
 */
import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  width: "1em",
  height: "1em",
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: false,
};

export function ChevronDown(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

export function ChevronUp(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M4 10l4-4 4 4" />
    </svg>
  );
}

export function ChevronRight(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

export function Check(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M3.5 8.5l3 3 6-7" />
    </svg>
  );
}

export function Close(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

export function Sun(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.5v1.5M8 13v1.5M2.4 2.4l1 1M12.6 12.6l-1-1M1.5 8h1.5M13 8h1.5M2.4 13.6l1-1M12.6 3.4l-1 1" />
    </svg>
  );
}

export function Moon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M13 9.3A5.5 5.5 0 1 1 6.7 3a4.5 4.5 0 0 0 6.3 6.3z" />
    </svg>
  );
}

export function Monitor(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <rect x="2" y="3" width="12" height="8" rx="1" />
      <path d="M6 13.5h4M8 11v2.5" />
    </svg>
  );
}
