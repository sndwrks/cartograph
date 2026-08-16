# Slice 12 — SPA side panel

## Goal

The persistent right panel becomes the workspace's second half: by default a god-node list scoped to the current view, and when a node is selected, a full detail card — summary, location, metrics, grouped edges with confidence badges, plus slots (hidden until their slices land) for related KB terms and message threads. M3 completes with this slice.

## Depends on

Slice 11 (selection state, navigation targets).

## Spec references

`initial-spec.md` §7 (side panel — both states, caution glyph, confidence badges).

## Requirements

### 1. Default state — god-node list (`SidePanel` → `GodNodeList.tsx`)

1. Data: `GET /god-nodes?repo=&limit=20` on the overview; `GET /god-nodes?repo=&community_id=` after drill-in (community-scoped); in ego view, keep the last scope.
2. Each row: kind badge (theme colors), name, importance meter derived from pagerank (normalized to the max in the current list), `in/out` degree as `↓12 ↑3`, one-line summary (dimmed "no summary yet" fallback until slice 13 populates them).
3. **Caution glyph:** rows where `degree_in > threshold` get a ⚠ marker with tooltip "High fan-in — change carefully". Threshold from a build-time env default (`VITE_CAUTION_IN_DEGREE`, default 10) overridable in a small panel settings popover.
4. Clicking a row focuses that node on the canvas: in community/ego views pan+highlight if present, else navigate to the node's ego view. Also selects it (switches the panel to detail).

### 2. Detail state — `NodeDetail.tsx` (when `selectedNodeId` set)

Data: `GET /nodes/{id}` (+ already-loaded graph data). Sections top to bottom:

1. **Header:** kind badge, name, qualified name (copy-on-click), close button (back to god-node list).
2. **Summary:** node summary or "not yet summarized".
3. **Location:** `file_path:start_line–end_line`, monospace, copy-on-click.
4. **Metrics:** pagerank, in/out degree, community (label, clickable → drill-in).
5. **Edges:** grouped by rel (`calls`, `imports`, `inherits`, `references`, in and out separately, from `edge_counts` + an edges fetch via the ego endpoint at hops=1): each group collapsible, each edge row shows the other node's name (clickable → select + focus) and a **confidence badge** — colored pill using the same theme constants as the line styles (`resolved` solid/green-ish, `llm_inferred` dashed-styled/amber, `name_match` dotted-styled/gray). Counts shown per group header.
6. **Related KB terms** — render the section header with "requires enrichment (slice 13)" placeholder; wired when the API exposes it (slice 13 adds `GET /nodes/{id}/related-kb`).
7. **Discussion** — same pattern: section shell now, threads wired in slice 14.
8. "Expand ego graph" button (the slice-11 affordance lives here canonically).

### 3. Behavior

- Panel state follows the store: `selectedNodeId` null ⇒ list state; set ⇒ detail. Esc deselects. Selection survives view changes (navigating overview → community keeps the detail open if the node still exists).
- All panel data through TanStack Query with sane staleness (30s) — no bespoke fetch logic.

## Files

- `web/src/components/{SidePanel.tsx (real implementation),GodNodeList.tsx,NodeDetail.tsx,ConfidenceBadge.tsx,KindBadge.tsx}`
- `web/src/api/client.ts` (+ god-nodes, node-detail calls)

## Acceptance criteria

Against ingested + clustered `py_sample`:

1. Overview shows the repo-wide god-node list ordered by importance; drilling into a community re-scopes the list (different membership); a known high-fan-in fixture node shows the ⚠ glyph, and lowering the threshold in the settings popover adds glyphs live.
2. Clicking a god-node row inside its community view pans/highlights without a route change; clicking one from the overview navigates to ego view. Both select it and flip the panel to detail.
3. Detail card shows correct location and metrics for a hand-checked fixture symbol; edge groups match the node's known edges; every edge row has a confidence badge; clicking a neighbor selects it (panel updates in place).
4. Esc returns to the list; the KB and Discussion sections render as labeled placeholders, not errors.
5. `npm run build` clean; the full click-path (overview → drill-in → select → neighbor-hop → ego → Esc) produces no console errors.

## Out of scope

- Related-KB population and summaries content (slice 13).
- Message threads content (slice 14).
- Any node editing — the SPA is read-only over the graph.
