import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useRepoUuid } from "../hooks/useRepoUuid";
import { useRepos } from "../hooks/useRepos";
import { boardPath, graphPath, isGraphRoute, kbPath, repoPath, rescopePath } from "../routes";
import { GraphMark } from "./Logo";
import {
  PageTab,
  PageTabs,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui";
import styles from "./TopBar.module.css";

export default function TopBar() {
  const navigate = useNavigate();
  const { repos } = useRepos();
  const { pathname } = useLocation();
  // The URL is the source of truth for which repo is selected. On `/` and
  // legacy paths (one redirect frame) there is no uuid yet; fall back to the
  // first repo so the bar's links are still real links.
  const uuid = useRepoUuid() ?? repos[0]?.uuid;

  return (
    <header className={styles.topBar}>
      <button
        type="button"
        className={styles.title}
        onClick={() => navigate(uuid ? repoPath(uuid) : "/")}
      >
        <GraphMark className={styles.mark} />
        Cartograph
      </button>
      {uuid && (
        <>
          <PageTabs label="sections" className={styles.tabs}>
            {/* `end`: the dashboard is the index of /repo/:uuid, so without it
                this tab would be active under every child route. */}
            <NavLink to={repoPath(uuid)} end className={styles.tabLink}>
              {({ isActive }) => <PageTab label="usage" active={isActive} />}
            </NavLink>
            {/* `/c/:id` and `/n/:id` are siblings of `/graph`, not children, so
                no single NavLink `to`/`end` combination can cover all three:
                `end` only tightens matching, it can never broaden it across
                sibling routes. The graph section is therefore unioned by hand
                (routes.ts isGraphRoute) and the render-prop's own isActive
                ignored. */}
            <NavLink to={graphPath(uuid)} className={styles.tabLink}>
              {() => <PageTab label="graph" active={isGraphRoute(pathname)} />}
            </NavLink>
            {/* Unlike the graph section above, /kb's sub-pages (/kb/review,
                /kb/new, /kb/:id/edit) are real CHILDREN of /kb, so a non-`end`
                NavLink matches them all and isActive can be used directly.
                Don't hand-union this one. */}
            <NavLink to={kbPath(uuid)} className={styles.tabLink}>
              {({ isActive }) => <PageTab label="kb" active={isActive} />}
            </NavLink>
            <NavLink to={boardPath(uuid)} className={styles.tabLink}>
              {({ isActive }) => <PageTab label="board" active={isActive} />}
            </NavLink>
          </PageTabs>
          <div className={styles.repoSelect}>
            repo
            {/* Switching repos is a navigation, not a store write: RepoScope
                owns the store. A push (not replace) so Back returns to the
                previous repo. The search string is dropped on purpose — a
                ?sel= names an entry of the old repo. */}
            <Select
              value={uuid}
              onValueChange={(next) => navigate(rescopePath(pathname, next))}
            >
              <SelectTrigger aria-label="repo">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {repos.map((r) => (
                  <SelectItem key={r.uuid} value={r.uuid}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}
    </header>
  );
}
