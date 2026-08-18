import styles from "./KbTypeBadge.module.css";

const KNOWN = new Set([
  "glossary",
  "specification",
  "decision",
  "convention",
  "runbook",
]);

/**
 * The entry type, as a colored pill. Mirrors KindBadge, including the
 * data-attribute selectors. A type the SPA has never heard of falls through to
 * the `unknown` colour rather than rendering unstyled — adding a type on the
 * backend must not need a frontend release.
 */
export default function KbTypeBadge({ type }: { type: string }) {
  return (
    <span className={styles.badge} data-type={KNOWN.has(type) ? type : "unknown"}>
      {type}
    </span>
  );
}
