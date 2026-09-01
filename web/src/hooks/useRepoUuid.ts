import { useMatch } from "react-router-dom";

import { REPO_SCOPE } from "../routes";

/**
 * The uuid segment of the current /repo/<uuid>/… URL, or null outside it.
 *
 * `useMatch` rather than `useParams`: TopBar, the SidePanel subtree and the
 * search palette all render OUTSIDE `<Routes>`, where `useParams()` is empty.
 * A match against the location works anywhere under the router and is true
 * on the very first render, before RepoScope's effect has written the store.
 */
export function useRepoUuid(): string | null {
  return useMatch({ path: REPO_SCOPE, end: false })?.params.repoUuid ?? null;
}
