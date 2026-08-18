import type { ComponentProps } from "react";
import { Separator as Primitive } from "radix-ui";
import { cx } from "./cx";
import styles from "./Separator.module.css";

export function Separator({ className, ...props }: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root className={cx(styles.separator, className)} {...props} />;
}
