import type { ComponentProps } from "react";
import { cx } from "./cx";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "default" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg" | "icon" | "iconSm";

export interface ButtonProps extends ComponentProps<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/**
 * The kit's only non-Radix interactive primitive (Radix has no button).
 * Compose it into Radix triggers with `asChild`:
 *   <DialogTrigger asChild><Button>Open</Button></DialogTrigger>
 * Defaults to type="button" so it never accidentally submits a form.
 */
export function Button({
  variant = "default",
  size = "md",
  type = "button",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(styles.button, styles[variant], size !== "md" && styles[size], className)}
      {...props}
    />
  );
}
