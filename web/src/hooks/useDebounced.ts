import { useEffect, useState } from "react";

/**
 * The previous value of `value`, updated only after `delayMs` of quiet.
 *
 * Used to keep a text input off the query key: without it every keystroke is a
 * fresh TanStack cache miss, and on the KB list each miss costs two unindexed
 * ILIKE scans (the page and its count).
 */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
