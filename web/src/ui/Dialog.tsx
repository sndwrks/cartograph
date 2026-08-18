import { useEffect, type ComponentProps } from "react";
import { Dialog as Primitive } from "radix-ui";
import { Close as CloseGlyph } from "./glyphs";
import { cx } from "./cx";
import { composePopperDismiss, installPopperTracker } from "./popperGuard";
import { useUiStrings } from "./uiStrings";
import styles from "./Dialog.module.css";

export function Dialog(props: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root {...props} />;
}

export function DialogTrigger(props: ComponentProps<typeof Primitive.Trigger>) {
  return <Primitive.Trigger {...props} />;
}

export function DialogClose(props: ComponentProps<typeof Primitive.Close>) {
  return <Primitive.Close {...props} />;
}

export function DialogContent({
  className,
  children,
  onPointerDownOutside,
  onInteractOutside,
  ...props
}: ComponentProps<typeof Primitive.Content>) {
  // Track open poppers while this dialog is mounted so the dismiss guard can tell
  // a click that closes an open dropdown from a plain backdrop click.
  useEffect(() => installPopperTracker(), []);
  const strings = useUiStrings();
  return (
    <Primitive.Portal>
      <Primitive.Overlay className={styles.overlay} />
      <Primitive.Content
        className={cx(styles.content, className)}
        // Keep the dialog open when interacting with a portaled Select/Dropdown/
        // Popover inside it (see popperGuard.ts).
        onPointerDownOutside={composePopperDismiss(onPointerDownOutside)}
        onInteractOutside={composePopperDismiss(onInteractOutside)}
        {...props}
      >
        {children}
        <Primitive.Close className={styles.close} aria-label={strings.close}>
          <CloseGlyph />
        </Primitive.Close>
      </Primitive.Content>
    </Primitive.Portal>
  );
}

export function DialogTitle({ className, ...props }: ComponentProps<typeof Primitive.Title>) {
  return <Primitive.Title className={cx(styles.title, className)} {...props} />;
}

export function DialogDescription({
  className,
  ...props
}: ComponentProps<typeof Primitive.Description>) {
  return <Primitive.Description className={cx(styles.description, className)} {...props} />;
}
