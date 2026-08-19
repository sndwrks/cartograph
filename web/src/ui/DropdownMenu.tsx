import type { ComponentProps } from "react";
import { DropdownMenu as Primitive } from "radix-ui";
import { cx } from "./cx";
import styles from "./DropdownMenu.module.css";

export function DropdownMenu(props: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root {...props} />;
}

export function DropdownMenuTrigger(props: ComponentProps<typeof Primitive.Trigger>) {
  return <Primitive.Trigger {...props} />;
}

export function DropdownMenuContent({
  className,
  align = "end",
  sideOffset = 4, // px — matches Select's popper gap (no --radix-dropdown-menu-* size var to key off)
  ...props
}: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        className={cx(styles.content, className)}
        align={align}
        sideOffset={sideOffset}
        {...props}
      />
    </Primitive.Portal>
  );
}

export interface DropdownMenuItemProps extends ComponentProps<typeof Primitive.Item> {
  variant?: "default" | "danger";
}

export function DropdownMenuItem({
  className,
  variant = "default",
  ...props
}: DropdownMenuItemProps) {
  return (
    <Primitive.Item
      className={cx(styles.item, variant === "danger" && styles.danger, className)}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof Primitive.Separator>) {
  return <Primitive.Separator className={cx(styles.separator, className)} {...props} />;
}
