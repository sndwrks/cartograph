// Every URL the app builds or inspects goes through here. The repo prefix
// (/repo/<uuid>/…) used to be three separate hand-rolled path regexes
// (RouteSync, the side-panel allowlist, TopBar's id-scoped check) that all
// had to agree; now one anchored matcher feeds them all. Deliberately no
// react-router import so this file is a plain module vitest can run in node.

import type { ViewState } from "./store";

/** `<Route path>` for the layout route that scopes everything to one repo. */
export const REPO_SCOPE = "/repo/:repoUuid";

/** Child patterns, relative to REPO_SCOPE, used verbatim in `<Route path>`. */
export const CHILD = {
  graph: "graph",
  community: "c/:communityId",
  node: "n/:nodeId",
  board: "board",
  kb: "kb",
  kbReview: "kb/review",
  kbNew: "kb/new",
  kbEdit: "kb/:entryId/edit",
} as const;

export const repoPath = (uuid: string) => `/repo/${encodeURIComponent(uuid)}`;
export const graphPath = (uuid: string) => `${repoPath(uuid)}/graph`;
export const communityPath = (uuid: string, id: number) =>
  `${repoPath(uuid)}/c/${id}`;
export const nodePath = (uuid: string, id: number) => `${repoPath(uuid)}/n/${id}`;
export const boardPath = (uuid: string) => `${repoPath(uuid)}/board`;
export const kbPath = (uuid: string, opts?: { sel?: number }) =>
  `${repoPath(uuid)}/kb${opts?.sel !== undefined ? `?sel=${opts.sel}` : ""}`;
export const kbReviewPath = (uuid: string) => `${repoPath(uuid)}/kb/review`;
export const kbNewPath = (uuid: string) => `${repoPath(uuid)}/kb/new`;
export const kbEditPath = (uuid: string, entryId: number) =>
  `${repoPath(uuid)}/kb/${entryId}/edit`;

// The one anchored matcher everything below derives from. `rest` keeps its
// leading slash ("" for the dashboard index) so child checks can anchor on it.
const SCOPED = /^\/repo\/([^/]+)(\/.*)?$/;

export function matchRepoScope(
  pathname: string,
): { uuid: string; rest: string } | null {
  const m = pathname.match(SCOPED);
  if (!m) return null;
  // A malformed escape (/repo/abc%/graph) throws from decodeURIComponent;
  // this runs during render with no error boundary above it, so treat it as
  // "not a repo URL" and let the root redirect take over.
  let uuid: string;
  try {
    uuid = decodeURIComponent(m[1]);
  } catch {
    return null;
  }
  return { uuid, rest: m[2] ?? "" };
}

/** The store's view for a URL — legacy (unprefixed) paths fall to overview. */
export function parseView(pathname: string): ViewState {
  const rest = matchRepoScope(pathname)?.rest ?? "";
  const community = rest.match(/^\/c\/(\d+)$/);
  if (community) return { mode: "community", id: Number(community[1]) };
  const node = rest.match(/^\/n\/(\d+)$/);
  if (node) return { mode: "ego", nodeId: Number(node[1]) };
  return { mode: "overview" };
}

// The side panel belongs to the GRAPH routes only — an allowlist, not a
// "not /board" denylist (the denylist went wrong at the second full-width
// page and rendered an empty panel on unmatched URLs). Anchored on `rest` so
// the dashboard index ("") and /graph/anything are both out.
export function isGraphRoute(pathname: string): boolean {
  const rest = matchRepoScope(pathname)?.rest ?? null;
  return rest !== null && /^\/(graph|c\/\d+|n\/\d+)$/.test(rest);
}

/** Routes whose URL embeds an id belonging to one specific repo. */
export function isIdScopedRoute(pathname: string): boolean {
  const rest = matchRepoScope(pathname)?.rest ?? null;
  return rest !== null && /^\/(c|n)\/\d+$/.test(rest);
}

/**
 * The same page under a different repo. Id-scoped pages can't carry over —
 * a community or node id belongs to the old repo — so they land on the new
 * repo's graph; anything unscoped or unknown lands on its dashboard.
 */
export function rescopePath(pathname: string, uuid: string): string {
  const scope = matchRepoScope(pathname);
  if (!scope) return repoPath(uuid);
  if (isIdScopedRoute(pathname)) return graphPath(uuid);
  return `${repoPath(uuid)}${scope.rest}`;
}

/**
 * Pre-prefix section roots that bookmarks may still carry. App.tsx mounts a
 * redirect at `${root}/*` for each — a splat also matches the bare root, so
 * one entry covers /kb, /kb/review, /kb/9/edit and /c/12 alike. Keep this
 * the single list: nothing else enumerates the legacy routes.
 */
export const LEGACY_ROUTES = ["/graph", "/board", "/kb", "/c", "/n"] as const;

/**
 * A legacy path is exactly the scoped suffix, so prefixing it is enough;
 * the search string rides along so `/kb?sel=3` keeps its selection.
 */
export function legacyToScoped(
  pathname: string,
  search: string,
  uuid: string,
): string {
  return `${repoPath(uuid)}${pathname}${search}`;
}
