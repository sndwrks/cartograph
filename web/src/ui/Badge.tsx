import type { ComponentProps } from "react";
import { cx } from "./cx";
import styles from "./Badge.module.css";

export type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

export interface BadgeProps extends ComponentProps<"span"> {
  variant?: BadgeVariant;
}

/**
 * Small inline status pill / tag. Used for row badges (e.g. an `is_sndwrks`
 * flag, an invoice status) and filter chips. Variants map to the status tokens.
 */
export function Badge({ variant = "default", className, ...props }: BadgeProps) {
  return <span className={cx(styles.badge, styles[variant], className)} {...props} />;
}
