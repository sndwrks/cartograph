import type { ComponentProps } from "react";
import { cx } from "./cx";
import styles from "./Input.module.css";

export type InputProps = ComponentProps<"input">;

/**
 * Styled text input. Radix has no input primitive, so this is a thin wrapper
 * over the native element (like Button) styled with the design tokens. Defaults
 * to type="text". Compose a <Label> with `htmlFor` for accessibility.
 */
export function Input({ className, type = "text", ...props }: InputProps) {
  return <input type={type} className={cx(styles.input, className)} {...props} />;
}
