import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { VisuallyHidden } from "radix-ui";

import { searchCode } from "../api/client";
import type { NodeKind } from "../api/types";
import { useAppStore } from "../store";
import { cx, Dialog, DialogContent, DialogDescription, DialogTitle } from "../ui";
import KindBadge from "./KindBadge";
import styles from "./SearchPalette.module.css";

const FILTERABLE_KINDS: NodeKind[] = [
  "class",
  "function",
  "method",
  "module",
  "doc",
  "config",
];

function useDebounced(value: string, delayMs: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export default function SearchPalette() {
  const [input, setInput] = useState("");
  const [kinds, setKinds] = useState<Set<NodeKind>>(new Set());
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const repo = useAppStore((state) => state.repo);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);
  const paletteOpen = useAppStore((state) => state.paletteOpen);
  const setPaletteOpen = useAppStore((state) => state.setPaletteOpen);
  const navigate = useNavigate();

  const debouncedQuery = useDebounced(input, 200);
  const kindsParam = kinds.size > 0 ? [...kinds].join(",") : undefined;

  const query = useQuery({
    queryKey: ["search", repo, debouncedQuery, kindsParam],
    queryFn: () =>
      searchCode(debouncedQuery, {
        repo: repo ?? undefined,
        mode: "hybrid",
        kinds: kindsParam,
      }),
    enabled: paletteOpen && debouncedQuery.trim().length > 0,
  });
  const results = query.data?.results ?? [];
  const maxScore = Math.max(...results.map((r) => r.score), 1e-9);

  // Global ⌘K / Ctrl-K toggle. Escape-to-close and the focus trap are handled
  // by Dialog (Radix) now, so this listener only owns the open shortcut. Reads
  // the store directly rather than depending on `paletteOpen` so the listener
  // doesn't need to be re-registered on every open/close.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(!useAppStore.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setPaletteOpen]);

  useEffect(() => {
    if (paletteOpen) {
      setInput("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [paletteOpen]);

  useEffect(() => setActiveIndex(0), [debouncedQuery, kindsParam]);

  const choose = (index: number) => {
    const result = results[index];
    if (!result) return;
    setSelectedNodeId(result.node.id);
    setPaletteOpen(false);
    navigate(`/n/${result.node.id}`);
  };

  return (
    <Dialog open={paletteOpen} onOpenChange={setPaletteOpen}>
      <DialogContent
        className={styles.content}
        // The palette consumes its own Escape. SidePanel also listens for
        // Escape on `window` to deselect the current node; without this,
        // closing the palette would deselect at the same time. Radix listens
        // on `document`, which bubbles first, so stopping propagation here
        // reaches SidePanel's listener in time — whereas relying on the
        // `paletteOpen` store value racing back through React does not.
        onEscapeKeyDown={(event) => event.stopPropagation()}
      >
        <VisuallyHidden.Root>
          <DialogTitle>Search code entities</DialogTitle>
          <DialogDescription>
            Search across indexed code entities. Use the arrow keys to
            navigate results and Enter to open the selected result.
          </DialogDescription>
        </VisuallyHidden.Root>
        <input
          ref={inputRef}
          className={styles.input}
          value={input}
          placeholder="Search code entities…"
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((index) => Math.min(index + 1, results.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(activeIndex);
            }
          }}
        />
        <div className={styles.kindChips}>
          {FILTERABLE_KINDS.map((kind) => {
            const active = kinds.has(kind);
            return (
              <button
                key={kind}
                type="button"
                className={cx(styles.chip, active && styles.chipActive)}
                data-kind={active ? kind : undefined}
                onClick={() =>
                  setKinds((previous) => {
                    const next = new Set(previous);
                    if (next.has(kind)) next.delete(kind);
                    else next.add(kind);
                    return next;
                  })
                }
              >
                {kind}
              </button>
            );
          })}
        </div>
        <ul className={styles.results}>
          {results.map((result, index) => (
            <li
              key={result.node.id}
              className={cx(styles.result, index === activeIndex && styles.resultActive)}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(index)}
            >
              <KindBadge kind={result.node.kind} />
              <span className={styles.resultName}>{result.node.name}</span>
              <span className={cx(styles.resultQname, "muted")}>
                {result.node.qualified_name}
              </span>
              <span className={cx(styles.resultPath, "muted")}>
                {result.node.file_path ?? ""}
              </span>
              <span className={styles.scoreBar}>
                <span
                  className={styles.scoreFill}
                  style={{ width: `${(result.score / maxScore) * 100}%` }}
                />
              </span>
            </li>
          ))}
          {debouncedQuery.trim().length > 0 &&
            !query.isPending &&
            results.length === 0 && (
              <li className={cx(styles.empty, "muted")}>No matches.</li>
            )}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
