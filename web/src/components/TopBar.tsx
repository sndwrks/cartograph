import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { repoList, useAppStore } from "../store";
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
  const repo = useAppStore((state) => state.repo);
  const setRepo = useAppStore((state) => state.setRepo);
  const navigate = useNavigate();
  const repos = repoList();
  const { pathname } = useLocation();

  // `/c/:id` and `/n/:id` are siblings of `/graph`, not children, so no single
  // NavLink `to`/`end` combination can cover all three: `end` only tightens
  // matching, it can never broaden it across sibling routes. The graph section
  // is therefore unioned by hand and the render-prop's own `isActive` ignored.
  // Routes whose URL embeds an id belonging to one specific repo.
  const idScopedRoute =
    pathname.startsWith("/c/") || pathname.startsWith("/n/");
  const graphActive = pathname === "/graph" || idScopedRoute;

  return (
    <header className={styles.topBar}>
      <button
        type="button"
        className={styles.title}
        onClick={() => navigate("/graph")}
      >
        <GraphMark className={styles.mark} />
        Cartograph
      </button>
      <PageTabs label="sections" className={styles.tabs}>
        <NavLink to="/graph" className={styles.tabLink}>
          {() => <PageTab label="graph" active={graphActive} />}
        </NavLink>
        {/* Unlike the graph section above, /kb's sub-pages (/kb/review,
            /kb/new, /kb/:id/edit) are real CHILDREN of /kb, so a non-`end`
            NavLink matches them all and isActive can be used directly. Don't
            hand-union this one. */}
        <NavLink to="/kb" className={styles.tabLink}>
          {({ isActive }) => <PageTab label="kb" active={isActive} />}
        </NavLink>
        <NavLink to="/board" className={styles.tabLink}>
          {({ isActive }) => <PageTab label="board" active={isActive} />}
        </NavLink>
      </PageTabs>
      <div className={styles.repoSelect}>
        repo
        <Select
          value={repo ?? ""}
          onValueChange={(value) => {
            setRepo(value || null);
            // Stay where you are. Only the routes carrying a repo-specific id
            // have to be left behind — a community or node id from the old repo
            // would 404 against the new one. `/graph` and `/board` both scope
            // themselves by the store's repo, so they just refetch in place.
            if (idScopedRoute) navigate("/graph");
          }}
        >
          <SelectTrigger aria-label="repo">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {repos.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </header>
  );
}
