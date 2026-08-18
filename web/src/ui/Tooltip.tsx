import type { ComponentProps } from "react";
import { Tooltip as Primitive } from "radix-ui";
import { cx } from "./cx";
import styles from "./Tooltip.module.css";

/** Wrap the app (or a subtree) once in <TooltipProvider> for shared timing. */
export function TooltipProvider(props: ComponentProps<typeof Primitive.Provider>) {
  return <Primitive.Provider {...props} />;
}

export function Tooltip(props: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root {...props} />;
}

export function TooltipTrigger(props: ComponentProps<typeof Primitive.Trigger>) {
  return <Primitive.Trigger {...props} />;
}

export function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        className={cx(styles.content, className)}
        sideOffset={sideOffset}
        {...props}
      >
        {children}
        <Primitive.Arrow className={styles.arrow} />
      </Primitive.Content>
    </Primitive.Portal>
  );
}
