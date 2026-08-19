# Slice 18 — SPA knowledge-base page

## Goal

A `/kb` section in the SPA: browse entries of any type with a per-type detail view, review and publish or reject agent proposals, and create or edit entries by hand. This is the app's first write surface — everything before it is read-only — so it also establishes the mutation pattern, adds the one missing `ui/` primitive, and fixes two latent bugs in the API client and the route shell that this page would otherwise trip over.

## Depends on

Slices 15 (typed API, `GET /kb/types`) and 16 (publish / reject / archive endpoints, the proposal queue). Slice 12 (the side panel this page deliberately gates out).

## Spec references

`initial-spec.md` §7 (SPA structure; TanStack Query for server data, a small Zustand store for view state). Read `web/src/views/BoardView.tsx` + `BoardView.module.css` before starting — it is the template for a full-width page — and the header comment block in `web/src/styles/tokens.css`, whose rules are binding.

## Requirements

### 1. Routes and the route shell — `App.tsx`

```
/kb               index + detail; selection lives in ?sel=<id>
/kb/review        the proposal queue
/kb/new           editor, blank
/kb/:entryId/edit editor, prefilled
```

Selection is a **search param, not a path segment**: the index and the detail share one fetch, and a path segment would force a second fetch path for nothing. It also makes the selection deep-linkable and back/forward-correct.

**Fix the side-panel gate rather than extending it.** `App.tsx:52` currently reads `showSidePanel = pathname !== "/board"`, which was right with one full-width page and is wrong with two — and it renders an empty panel on any unmatched URL. Invert to an allowlist:

```ts
// The side panel belongs to the graph routes only — it renders god nodes or
// node detail. Everything else (board, kb, and any unmatched URL) is a
// full-width page, and .workspace's `auto` track collapses with it absent.
const GRAPH_ROUTE = /^\/(graph|c\/\d+|n\/\d+)$/;
const showSidePanel = GRAPH_ROUTE.test(pathname);
```

`RouteSync` needs no change — `/kb*` falls through to `setView({mode:"overview"})`, which is inert while the graph is unmounted.

### 2. Nav — `components/TopBar.tsx`

One `NavLink` + `PageTab` chip labelled `kb`, between `graph` and `board`. Unlike the graph section, `/kb`'s sub-pages are real children of `/kb`, so a non-`end` `NavLink` matches them all and `isActive` can be used directly. **Comment the contrast** with the hand-unioned `graphActive` immediately above it, or the next reader will hand-union this one out of cargo cult.

### 3. Component tree

```
KbView                              web/src/views/KbView.tsx + .module.css
│  .kb grid-template-rows: auto minmax(0,1fr)     ← BoardView.module.css
├─ .header  h1 · type Select · filter Input · "N proposals" Badge → /kb/review
│           · Button primary → /kb/new
└─ .body    grid-template-columns: 22rem minmax(0,1fr)
   ├─ KbList                        web/src/components/kb/KbList.tsx
   │    grouped by type under h2 when type=all, flat when filtered
   │    row: KbTypeBadge · title · slug (mono) · alias count
   └─ KbEntryDetail                 web/src/components/kb/KbEntryDetail.tsx
      ├─ header  KbTypeBadge · title · slug · KbStatusBadge · repo scope · updated_at
      ├─ body    <pre> with white-space: pre-wrap — NOT a markdown renderer
      ├─ aliases Badge each
      └─ payload PAYLOAD_RENDERERS[type] ?? FallbackPayload
                 web/src/components/kb/payloads/index.tsx + five siblings

KbReviewView                        web/src/views/KbReviewView.tsx
└─ ProposalCard                     web/src/components/kb/ProposalCard.tsx
   ├─ meta: KbTypeBadge · slug · proposing agent · age
   └─ Publish | Edit & publish | Reject → Dialog + Textarea (reason required)

KbEditorView                        web/src/views/KbEditorView.tsx
   type Select (disabled when editing) · slug · title · aliases · body Textarea
   · payload JSON Textarea · repo Select (+ "global") · Save / Save & publish
```

**Five field sets in one page** is handled by a front-end registry keyed on the type string **with a fallback renderer**, mirroring the backend's `REGISTRY`. Every common field (type, slug, title, body, aliases, status, repo, timestamps) renders identically for all types; only the payload block dispatches. A sixth backend type then ships **without an SPA release** — it renders through `FallbackPayload`, a `<dl>` over the payload keys, until someone writes a nicer one. A single generic schema-driven renderer was rejected: five bespoke ~30-line layouts read far better, and readability is the entire point of a detail view.

The type `Select` is populated from `GET /kb/types`. **Never a hard-coded array of five names** — that endpoint exists precisely to make adding a type a backend-only change.

**The editor's payload field is a JSON `Textarea` in v1, and that is ugly — say so in the PR.** The clean version drives inputs off `/kb/types`'s payload JSON Schema; it is roughly 120 lines plus a widget-type mapping and can be added later against the same endpoint with no API change. Ship the textarea, let the server's 422 be the validator, and revisit when a human complains about hand-writing a decision's `alternatives[]`.

The editor is a **route, not a modal**: `Dialog.module.css` caps at `max-width: 28rem`, which is right for the reject-reason confirm and wrong for an editor. That mismatch is the argument for the route, not for a new dialog size.

### 4. `ui/` primitives

**`ui/Textarea.tsx` + `Textarea.module.css` + a line in `ui/index.ts` — the one new primitive, and it is unavoidable.** `Input.module.css` hard-codes `height: 2.25rem` with no `resize`, so reusing its class on a `<textarea>` yields a one-line box; body, reject-reason and payload JSON are all multi-line. Copy `Input.tsx` verbatim, swap the element, and set `min-height: 8rem; resize: vertical;` with `font-family: var(--font-mono)` on a `mono` variant for the payload field.

Not needed, and each rejection is deliberate:

- **Tabs** — type selection is URL state (`?type=`); Radix Tabs would move it into component state and kill deep links. Use `Select` (as `BoardView` does) or `PageTabs`.
- **Form / Label / Field** — a local `.field` class wrapping `<label>` + control, following `BoardView.module.css`'s `.filter`.
- **Toast** — the app has zero toasts today; adding a system for two mutations is scope creep. Mutation feedback is inline text beside the button.

### 5. Tokens — `styles/tokens.css`

`KbTypeBadge` mirrors `KindBadge.tsx` exactly (`data-type` attribute selectors, one color per type). Add a `--kb-type-*` block aliasing existing primitives — **never raw hex**:

```css
/* ───────── KB entry types ───────── */
--kb-type-glossary: var(--color-brand-purple-light);
--kb-type-specification: var(--color-info);
--kb-type-decision: var(--color-caution);
--kb-type-convention: var(--color-good);
--kb-type-runbook: var(--color-grey-500);
```

**Do not name these `--graph-*`** — `theme.ts` validates that namespace as 6-digit hex for canvas alpha-suffixing, and the naming would imply a canvas contract that does not exist. Because they resolve through theme-invariant primitives, the dark block needs no additions.

`.body`'s two columns must collapse. Literal px with the tagged comment, per the warning at `tokens.css:125-142`:

```css
@media (max-width: 960px) { /* --bp-md */
  .body { grid-template-columns: minmax(0, 1fr); }
}
```

`KbStatusBadge` picks `ui/Badge` variants **by rendered color, not by name** — `Badge.module.css:27-34` has `warning` and `danger` inverted relative to the tokens (`.warning` uses `--color-warn`, red; `.danger` uses `--color-caution`, yellow). Do not fix that here; it would silently recolor existing consumers.

### 6. API client — `api/client.ts`, `api/types.ts`

There is currently **no `post`, `put` or `delete` helper** — add three siblings to `get<T>` sharing one error path.

**Fix the error path while you are in it.** `client.ts:38-45` types FastAPI's `detail` as `string`, but a 422 sends an **array of objects** (`[{loc, msg, type}]`), so it assigns an array to a string field. The editor is the first screen that hits 422 routinely and would render `[object Object]`. Keep `ApiError.message` as a readable summary and add `ApiError.detail: unknown` carrying the parsed body, so `KbEditorView` can map `loc` → field and show the error beside the input.

New functions, one exported arrow each: `fetchKbEntries`, `fetchKbEntry`, `fetchKbTypes`, `createKbEntry`, `updateKbEntry`, `deleteKbEntry`, `publishKbEntry`, `rejectKbEntry`.

`api/types.ts` gains `KbEntryOut`, `KbTypeOut`, `KbStatus`, `KbTypeName` — and **`RelatedKbTerm` moves here** from its inline declaration at `client.ts:89-94`, which sits against that file's own stated convention that shapes live in `types.ts`.

### 7. Mutations

This is the app's first `useMutation`. Establish the pattern once, in `KbReviewView`: `useMutation` from `@tanstack/react-query` (already a dependency) with `onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kb"] })`, and **every KB query key prefixed `["kb", …]`** so one invalidate covers the list, the detail and the header's proposal count.

### 8. Graph wiring — `components/NodeDetail.tsx`

Roughly fifteen lines at 213-231. Each related-KB row gains a `KbTypeBadge` and becomes a `Link` to `/kb?sel={id}`; `RelatedKbTerm` picks up `id`, `type` and `slug` (slice 15 already returns them). **Keep the empty state string verbatim** — `"no related terms yet (requires enrichment)"`. Do not add a second "conventions for this repo" section; `/kb` is where you browse.

## Files

- `web/src/views/{KbView,KbReviewView,KbEditorView}.tsx` + `.module.css` siblings
- `web/src/components/kb/{KbList,KbEntryDetail,KbTypeBadge,KbStatusBadge,ProposalCard}.tsx` + `.module.css` siblings
- `web/src/components/kb/payloads/{index,Glossary,Specification,Decision,Convention,Runbook,Fallback}.tsx`
- `web/src/ui/{Textarea.tsx,Textarea.module.css,index.ts}`
- `web/src/{App.tsx,components/TopBar.tsx,components/NodeDetail.tsx,api/client.ts,api/types.ts,styles/tokens.css}`

## Acceptance criteria

There is no frontend test runner and this slice does not add one — vitest plus testing-library for one page is a larger change than the page. The net is the type checker plus a recorded manual pass.

1. `npm run build` clean. `tsc -b` runs first, so this type-checks `api/types.ts` against every component — which is why `types.ts` must move in lockstep with `schemas.py` and must not be `any` anywhere.
2. `npm run lint` clean (oxlint).
3. Manual pass, driven through the Playwright MCP already in use here (`.playwright-mcp/` holds prior artifacts), recorded in the PR:
   1. `/kb` loads; the type Select is populated from `/kb/types` — prove it by adding a sixth type server-side and seeing it appear with **no frontend rebuild**.
   2. Filtering by type narrows the list; `all` groups by type under headings.
   3. Clicking a row opens the detail and the payload renders through its per-type renderer.
   4. **A row with an unrecognised type renders through `FallbackPayload` rather than crashing** — force it by hand-inserting `type='experiment'`. This is the single most valuable check here, because it is the one that decides whether the next backend type needs an SPA release.
   5. `?sel=<id>` deep-links, and browser back returns to the previous selection.
   6. The header's proposal count matches `/kb/review`, and publishing one decrements it with no manual refresh — this is what proves the `["kb", …]` invalidate.
   7. Reject with an empty reason is blocked; with a reason, the card leaves the queue.
   8. Bad payload JSON in the editor shows an **inline field error, not `[object Object]`** — the §6 fix.
   9. `NodeDetail`'s related KB terms show a type badge and link into `/kb`.
   10. At 900px the two-column body collapses to one — which also proves the literal-px media query, since a `var(--bp-md)` in the condition would fail here silently.
4. The side panel is absent on `/kb` **and** on an unmatched URL, and still present on `/graph`, `/c/:id`, `/n/:id`.
5. Do **not** test light mode — `web/index.html` hard-codes `data-theme="dark"` and `theme.ts` documents the app as dark-only, so a light-mode check would be testing an unreachable state.

## Out of scope

- A schema-driven payload editor (§3 records the upgrade path).
- A markdown renderer for entry bodies — `<pre>` with `pre-wrap` until someone asks.
- Triggering an export from the UI (slice 17's CLI is the only entry point).
- Removing the legacy `term`/`definition`/`category` fields from the API — a follow-up once this page is the only consumer.
- Any frontend test runner.
