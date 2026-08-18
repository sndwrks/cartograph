/**
 * Tiny className joiner — keeps the kit dependency-free (no clsx/classnames).
 * Falsy parts are dropped so `cx(styles.base, active && styles.active)` works.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
