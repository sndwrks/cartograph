# Slice 10 — SPA shell & overview view

## Goal

The real SPA replaces the slice-01 placeholder: a single workspace page with a main graph canvas and a persistent right side panel (placeholder content this slice), state via TanStack Query + Zustand, rendering via react-force-graph. The overview view works: communities as super-nodes, aggregated edges, hover summaries, click-to-navigate stubs.

## Depends on

Slice 07 (`/overview` endpoint). Ship against an ingested + clustered repo.

## Spec references

`initial-spec.md` §7 (SPA architecture, overview view, panel skeleton).

## Requirements

### 1. Foundation

1. Dependencies: `@tanstack/react-query`, `zustand`, `react-force-graph-2d` (WebGL/canvas renderer from the react-force-graph family; 2d is sufficient and lighter than 3d), `react-router-dom`. TypeScript strict.
2. **API client** (`src/api/`): typed fetch wrappers for every slice-07 endpoint, base path `/api/v1` (relative — the nginx/Vite proxy handles routing). Response types mirror slice-07 schemas exactly; define them once in `src/api/types.ts` (`NodeOut`, `EdgeOut`, `CommunityOut`, `CommunityEdgeOut`, confidence union type `"resolved" | "llm_inferred" | "name_match"`).
3. **Zustand store** (`src/store.ts`): `{ repo: string | null, view: {mode: "overview"} | {mode: "community", id: number} | {mode: "ego", nodeId: number}, selectedNodeId: number | null, hopDepth: number, minConfidence: Confidence | null }` with setter actions. Server data never lives here — TanStack Query owns it.
4. **Routing:** URL reflects view state (`/`, `/c/:communityId`, `/n/:nodeId`) so views are linkable; store syncs from the route.
5. **Layout** (`src/App.tsx`): top bar (repo selector — populated from a small `GET /overview` probe or hardcoded repo list env; app title), main canvas area, right side panel (fixed ~340px, renders "select a node" placeholder — slice 12 fills it).

### 2. Overview view — `src/views/Overview.tsx`

1. Data: `useQuery(["overview", repo])` → communities + community edges. Typically dozens of items; render immediately, no pagination.
2. Render with react-force-graph: one graph node per community, **sized by `node_count`** (area-proportional radius, clamped to a sane min/max), labeled with `label ?? "community #" + id`; one link per community edge with **width scaled by `weight`** (log scale, clamped).
3. Hover a super-node → tooltip with label + `summary` (or "no summary yet") + node/edge counts.
4. Click a super-node → navigate to `/c/:id` (slice 11 implements the view; until then the route renders a "drill-in coming in slice 11" placeholder — the navigation itself must work).
5. Empty state: repo with no communities → message instructing to run ingest + metrics jobs (show the two compose commands).

### 3. Visual conventions started here

`src/theme.ts`: node-kind color map (used from slice 11 on), confidence → line-style map (`resolved` solid, `llm_inferred` dashed, `name_match` dotted) exported as constants so every later slice imports the same source of truth.

### 4. Build & serve

The slice-01 web Dockerfile keeps working (`npm run build` → nginx). Dev override runs Vite with the `/api` proxy. No CORS anywhere — same-origin via proxy is the contract.

## Files

- `web/src/{App.tsx,main.tsx,store.ts,theme.ts}`
- `web/src/api/{client.ts,types.ts}`
- `web/src/views/Overview.tsx`, `web/src/components/{TopBar.tsx,SidePanel.tsx (placeholder),GraphCanvas.tsx}`
- `web/package.json` (deps)

## Acceptance criteria

1. `npm run build` succeeds with strict TypeScript; `docker compose up --build` serves the SPA at `localhost:5173`.
2. Against the ingested + clustered `py_sample` repo: overview renders its communities as sized super-nodes with edges; hover shows the tooltip; click navigates to `/c/:id` (placeholder page) and browser back returns to the overview.
3. With an unknown/empty repo the empty state renders (no crash, no blank canvas).
4. `npm run dev` against the compose api works via proxy (no CORS errors in console).
5. Reloading `/c/3` directly deep-links (route → store sync works).

## Out of scope

- Community drill-in rendering, ego view, search palette (slice 11).
- Side panel content (slice 12).
- Confidence-styled node-level edges (no node-level edges render in the overview; the theme constants just get defined here).
