import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { fetchKbEntries, fetchKbEntry, fetchKbTypes } from "../api/client";
import KbEntryDetail from "../components/kb/KbEntryDetail";
import KbList from "../components/kb/KbList";
import { useDebounced } from "../hooks/useDebounced";
import { useAppStore } from "../store";
import {
  Badge,
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui";
import styles from "./KbView.module.css";
import viewFrameStyles from "./viewFrame.module.css";

// Radix Select.Item rejects an empty-string value (reserved to mean "no
// selection"), so "all types" round-trips through this sentinel — same
// precedent as BoardView's agent filter and EgoView's confidence filter.
const ANY_TYPE = "any";
const PAGE_LIMIT = 200;

export default function KbView() {
  const repo = useAppStore((state) => state.repo);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  // Selection and filters live in the URL, not component state, so the page
  // deep-links and browser back/forward move the selection.
  const type = params.get("type") ?? ANY_TYPE;
  const selectedId = params.get("sel") ? Number(params.get("sel")) : null;

  // The text box is local and debounced: on the query key, every keystroke is
  // a cache miss and each miss costs two unindexed ILIKE scans server-side.
  const [input, setInput] = useState(params.get("q") ?? "");
  const search = useDebounced(input, 200);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null || value === "" || value === ANY_TYPE) next.delete(key);
    else next.set(key, value);
    if (key !== "sel") next.delete("sel"); // a changed filter invalidates it
    setParams(next, { replace: key === "q" });
  };

  // mirror the settled search into the URL so the view is still linkable
  useEffect(() => {
    if ((params.get("q") ?? "") !== search) setParam("q", search || null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const types = useQuery({
    queryKey: ["kb", "types"],
    queryFn: fetchKbTypes,
    staleTime: 5 * 60_000,
  });

  const entries = useQuery({
    // `limit` belongs in the key: two callers asking the same question with
    // different page sizes must not share one cache entry.
    queryKey: ["kb", "entries", { type, repo, search, limit: PAGE_LIMIT }],
    queryFn: () =>
      fetchKbEntries({
        type: type === ANY_TYPE ? undefined : type,
        repo: repo ?? undefined,
        q: search || undefined,
        limit: PAGE_LIMIT,
      }),
  });

  const proposals = useQuery({
    queryKey: ["kb", "entries", { status: "proposed", repo, limit: 1 }],
    queryFn: () =>
      fetchKbEntries({ status: "proposed", repo: repo ?? undefined, limit: 1 }),
  });

  const rows = entries.data?.entries ?? [];
  // A plain scan, not useMemo: `rows` is a fresh array on every render, so
  // memoizing on it never hits, and the list is server-capped.
  const inPage = rows.find((entry) => entry.id === selectedId) ?? null;

  // A deep link can name an entry outside the current filter or page —
  // NodeDetail's related-KB links and the editor's post-save redirect both do.
  // Fetch it directly rather than rendering "Select an entry" at a valid URL.
  const fetched = useQuery({
    queryKey: ["kb", "entry", selectedId],
    queryFn: () => fetchKbEntry(selectedId as number),
    enabled: selectedId !== null && inPage === null,
  });

  const selected = inPage ?? fetched.data ?? null;
  const pending = proposals.data?.total ?? 0;
  const total = entries.data?.total ?? 0;
  const clipped = total > rows.length;

  return (
    <div className={styles.kb}>
      <div className={styles.header}>
        <h1 className={styles.title}>Knowledge base</h1>

        <label className={styles.filter}>
          type
          <Select value={type} onValueChange={(value) => setParam("type", value)}>
            <SelectTrigger aria-label="type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY_TYPE}>all types</SelectItem>
              {/* from GET /kb/types — never a hard-coded list, so a new
                  backend type appears with no frontend release */}
              {(types.data?.types ?? []).map((kbType) => (
                <SelectItem key={kbType.name} value={kbType.name}>
                  {kbType.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>

        <Input
          className={styles.search}
          type="search"
          placeholder="filter…"
          aria-label="filter entries"
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />

        <div className={styles.actions}>
          {pending > 0 && (
            <Button variant="ghost" onClick={() => navigate("/kb/review")}>
              <Badge variant="danger">{pending}</Badge>
              &nbsp;proposal{pending === 1 ? "" : "s"}
            </Button>
          )}
          <Button variant="primary" onClick={() => navigate("/kb/new")}>
            New entry
          </Button>
        </div>
      </div>

      <div className={styles.body}>
        <div className={styles.listPane}>
          {entries.isPending ? (
            <div className={viewFrameStyles.canvasMessage}>Loading…</div>
          ) : entries.isError ? (
            <div className={viewFrameStyles.canvasMessage}>
              Failed to load entries: {String(entries.error)}
            </div>
          ) : (
            <>
              <KbList
                entries={rows}
                selectedId={selectedId}
                onSelect={(entry) => setParam("sel", String(entry.id))}
                grouped={type === ANY_TYPE}
              />
              {/* say when the list is partial rather than look complete */}
              {clipped && (
                <p className={styles.clipped}>
                  showing {rows.length} of {total} — narrow the filter to see the
                  rest
                </p>
              )}
            </>
          )}
        </div>
        <div className={styles.detailPane}>
          {fetched.isPending && selectedId !== null && inPage === null ? (
            <div className={viewFrameStyles.canvasMessage}>Loading…</div>
          ) : (
            <KbEntryDetail entry={selected} />
          )}
        </div>
      </div>
    </div>
  );
}
