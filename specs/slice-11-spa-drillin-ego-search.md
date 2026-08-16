# Slice 11 — SPA drill-in, ego view, search palette

## Goal

The canvas becomes fully navigable: clicking a community drills into its internal graph with ghosted stub edges to neighbors, any node can expand into its cross-community ego view, and a Cmd+K command palette searches the whole graph and jumps to results. Edge confidence is visually encoded on every rendered edge from here on.

## Depends on

Slice 10 (shell, canvas, theme constants, routing).

## Spec references

`initial-spec.md` §7 (drill-in, search, confidence line styles).

## Requirements

### 1. Community drill-in — `src/views/CommunityView.tsx` (replaces the slice-10 placeholder at `/c/:id`)

1. Data: `GET /communities/{id}/graph?limit=` (slice 07) → nodes, intra-community edges, stub edges.
2. Render nodes colored by kind (slice-10 `theme.ts` map), sized by pagerank (clamped); intra-community edges styled by confidence: **solid `resolved`, dashed `llm_inferred`, dotted `name_match`** (react-force-graph `linkLineDash` per link).
3. **Stub edges:** for each `{src_id, dst_community_id, weight}` render a short ghosted (low-opacity) edge from the src node to a small phantom marker labeled with the neighbor community's name. Clicking the phantom navigates to `/c/:dst_community_id`.
4. Breadcrumb bar: `Overview › <community label>`; clicking Overview returns to `/`.
5. Clicking a node sets `selectedNodeId` in the store (side panel consumes it in slice 12; until then the selection is just visually highlighted).
6. A limit control (top-N slider or select: 100/250/500) refetching with the new limit.

### 2. Ego view — `src/views/EgoView.tsx` at `/n/:nodeId`

1. Data: `GET /nodes/{id}/ego?hops=&limit=&min_confidence=` driven by store's `hopDepth` (control: 1/2/3) and `minConfidence` (control: All / ≥ llm_inferred / resolved only).
2. Center node visually distinguished (ring highlight); same kind colors and confidence line styles; crossing community boundaries is expected — color node halos by community id (subtle) so boundaries are visible.
3. Entry points: "expand ego graph" affordance on a selected node in the community view (button in the canvas context or panel later), and search results (below).
4. Breadcrumb: `Overview › <community> › <node name>` when arrived via drill-in; `Overview › <node name>` when arrived via search.

### 3. Search palette — `src/components/SearchPalette.tsx`

1. Omnipresent: Cmd+K (and Ctrl+K) opens a modal command palette from any view; Esc closes; up/down + Enter navigate.
2. Backed by `GET /search?q=&repo=&mode=hybrid` with 200ms debounce; render `degraded: true` responses identically (the field exists until slice 13 — ignore it visually).
3. Each result row: kind badge (colored), name, dimmed qualified name, file path, score bar; kind filter chips (class/function/method/module/doc/config) toggling the `kinds` param.
4. Selecting a result navigates to `/n/:nodeId` (ego view) and sets `selectedNodeId`.

### 4. Shared canvas mechanics

Refactor `GraphCanvas.tsx` so overview/community/ego views pass data + style callbacks rather than each owning a force-graph instance: one component handles zoom-to-fit on data change, hover tooltips, click handlers, dash-pattern rendering, and label visibility at zoom thresholds (labels only when < ~150 nodes or zoomed in).

## Files

- `web/src/views/{CommunityView.tsx,EgoView.tsx}`
- `web/src/components/{SearchPalette.tsx,Breadcrumbs.tsx,GraphCanvas.tsx (refactor)}`
- `web/src/api/client.ts` (+ ego/community/search calls if not present)

## Acceptance criteria

Verified against ingested + clustered `py_sample` (plus the seeded multi-confidence test repo if available):

1. Overview → click community → drill-in renders its nodes/edges; a `name_match` edge is visibly dotted, `resolved` solid (inspect a known fixture edge).
2. Stub edge phantom click lands on the neighboring community; breadcrumb returns to overview; browser back/forward traverse the history correctly.
3. Selecting a node then "expand ego graph" → `/n/:id` with the node ring-highlighted; hop control 1→2 grows the neighborhood; confidence filter set to "resolved only" removes the dotted edges.
4. Cmd+K from every view opens the palette; typing a fuzzy fragment (`ordr`) lists the expected symbol; Enter jumps to its ego view; kind filter excludes/includes correctly.
5. `npm run build` clean; no console errors during the full navigation loop.

## Out of scope

- Side panel detail/god-node content (slice 12) — selection state is set here, consumed there.
- KB terms, summaries, message threads in any view (slices 12–14).
