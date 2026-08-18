import type { ComponentProps } from "react";
import { cx } from "./cx";
import styles from "./Textarea.module.css";

export interface TextareaProps extends ComponentProps<"textarea"> {
  /** `mono` for code-ish content (JSON payloads); `default` for prose. */
  variant?: "default" | "mono";
}

/**
 * Multi-line text input. Not a variant of <Input>: that one hard-codes
 * `height: 2.25rem` with no `resize`, so reusing its class on a <textarea>
 * gives a one-line box. Styling otherwise mirrors it exactly.
 */
export function Textarea({ className, variant = "default", ...props }: TextareaProps) {
  return (
    <textarea className={cx(styles.textarea, styles[variant], className)} {...props} />
  );
}
