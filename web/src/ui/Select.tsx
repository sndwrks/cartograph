import type { ComponentProps } from "react";
import { Select as Primitive } from "radix-ui";
import { Check, ChevronDown, ChevronUp } from "./glyphs";
import { cx } from "./cx";
import styles from "./Select.module.css";

export function Select(props: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root {...props} />;
}

export function SelectGroup(props: ComponentProps<typeof Primitive.Group>) {
  return <Primitive.Group {...props} />;
}

export function SelectValue(props: ComponentProps<typeof Primitive.Value>) {
  return <Primitive.Value {...props} />;
}

export function SelectTrigger({
  className,
  children,
  ...props
}: ComponentProps<typeof Primitive.Trigger>) {
  return (
    <Primitive.Trigger className={cx(styles.trigger, className)} {...props}>
      {children}
      <Primitive.Icon className={styles.icon}>
        <ChevronDown />
      </Primitive.Icon>
    </Primitive.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  position = "popper",
  ...props
}: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content className={cx(styles.content, className)} position={position} {...props}>
        <Primitive.ScrollUpButton className={styles.scrollButton}>
          <ChevronUp />
        </Primitive.ScrollUpButton>
        <Primitive.Viewport className={styles.viewport}>{children}</Primitive.Viewport>
        <Primitive.ScrollDownButton className={styles.scrollButton}>
          <ChevronDown />
        </Primitive.ScrollDownButton>
      </Primitive.Content>
    </Primitive.Portal>
  );
}

export function SelectItem({
  className,
  children,
  ...props
}: ComponentProps<typeof Primitive.Item>) {
  return (
    <Primitive.Item className={cx(styles.item, className)} {...props}>
      <Primitive.ItemText>{children}</Primitive.ItemText>
      <Primitive.ItemIndicator className={styles.itemIndicator}>
        <Check />
      </Primitive.ItemIndicator>
    </Primitive.Item>
  );
}

export function SelectLabel({ className, ...props }: ComponentProps<typeof Primitive.Label>) {
  return <Primitive.Label className={cx(styles.label, className)} {...props} />;
}

export function SelectSeparator({
  className,
  ...props
}: ComponentProps<typeof Primitive.Separator>) {
  return <Primitive.Separator className={cx(styles.separator, className)} {...props} />;
}
