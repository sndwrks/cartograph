// A modal Dialog/Drawer that contains a Select, DropdownMenu, or Popover has a
// problem: those components portal their content to `document.body`, OUTSIDE the
// modal's own content subtree. When you click an item in that portaled popper,
// Radix's dismissable layer reads the pointer-down as an interaction OUTSIDE the
// modal and closes it. The fix is to detect interactions that originate inside a
// Radix popper (its wrapper carries `data-radix-popper-content-wrapper`) and
// prevent the dismiss so the modal stays open.

// The shape shared by Radix's PointerDownOutsideEvent / FocusOutsideEvent /
// InteractOutsideEvent — all CustomEvents carrying the real DOM event under
// `detail.originalEvent`.
interface DismissableEvent {
  readonly target: EventTarget | null;
  readonly defaultPrevented: boolean;
  readonly detail?: { readonly originalEvent?: Event };
  preventDefault: () => void;
}

const POPPER_SELECTOR = "[data-radix-popper-content-wrapper]";

// A popper counts as open unless its content (the wrapper's direct child, which
// carries Radix's `data-state`) is mid-exit-animation (`data-state="closed"`).
// A missing attribute counts as open — better to keep a modal alive one extra
// click than to dismiss it out from under the user.
//
// LIMITATION: the check is document-global by necessity — the popper is portaled
// to `document.body`, outside the modal's subtree, so there is nothing tighter to
// scope it to. A popper open ANYWHERE on the page (say a keyboard-focus-held
// Tooltip or a HoverCard outside the modal) also counts and will swallow one
// backdrop click. That mis-fire is rare and self-healing: the popper closes on
// that click, so the next one dismisses normally.
const anyPopperOpen = (): boolean =>
  typeof document !== "undefined" &&
  Array.from(document.querySelectorAll(POPPER_SELECTOR)).some(
    (wrapper) => wrapper.firstElementChild?.getAttribute("data-state") !== "closed",
  );

const originatesInPopper = (event: DismissableEvent): boolean => {
  const target = (event.detail?.originalEvent?.target ?? event.target) as Element | null;
  return target?.closest?.(POPPER_SELECTOR) != null;
};

// A portaled popper (Select/Dropdown/Popover) closes on the SAME outside pointer-
// down that the enclosing Dialog also treats as a dismiss — but the popper is torn
// out of the DOM before the Dialog's dismiss handler runs, so an at-dismiss-time
// DOM check finds nothing. We snapshot "was a popper open?" during the capture
// phase of the pointerdown (which fires BEFORE Radix's own handlers, while the
// popper is still mounted), then consult that snapshot when the Dialog dismiss
// fires later in the same event. This lets a plain backdrop click still close the
// dialog while a click that was really dismissing an open dropdown does not.
//
// The snapshot is keyed to the pointerdown Event object itself: the guard only
// honors it when the dismiss's `detail.originalEvent` IS that pointerdown. A
// dismiss driven by anything else (e.g. a focus-outside with no preceding click)
// never sees a stale `true` left over from an earlier interaction.
let pointerDownWithPopperOpen: Event | null = null;
let trackerRefs = 0;

const onPointerDownCapture = (event: Event): void => {
  pointerDownWithPopperOpen = anyPopperOpen() ? event : null;
};

// Ref-counted installer — Dialog/Drawer content calls this while mounted. The
// single document listener is shared across every open modal and removed when the
// last one unmounts.
export function installPopperTracker(): () => void {
  if (typeof document !== "undefined" && trackerRefs === 0) {
    document.addEventListener("pointerdown", onPointerDownCapture, true);
  }
  trackerRefs += 1;
  return () => {
    trackerRefs -= 1;
    if (typeof document !== "undefined" && trackerRefs === 0) {
      document.removeEventListener("pointerdown", onPointerDownCapture, true);
    }
  };
}

// Wrap an outside-interaction handler so a caller's handler runs first, then —
// unless it (or the guard) already prevented default — we suppress the dismiss
// when the interaction came from a portaled popper OR a popper was open at the
// exact pointer-down that triggered this dismiss (the click-out-of-an-open-
// dropdown case).
//
// The caller's handler can `preventDefault()` to keep the modal open on its own
// terms, but there is deliberately no hook to FORCE a dismiss the guard would
// suppress — no consumer has needed one; add an opt-out prop if that changes.
export function composePopperDismiss<E extends DismissableEvent>(
  handler: ((event: E) => void) | undefined,
): (event: E) => void {
  return (event) => {
    handler?.(event);
    if (event.defaultPrevented) return;
    const fromGuardedPointerDown =
      pointerDownWithPopperOpen != null &&
      event.detail?.originalEvent === pointerDownWithPopperOpen;
    if (originatesInPopper(event) || fromGuardedPointerDown) event.preventDefault();
  };
}
