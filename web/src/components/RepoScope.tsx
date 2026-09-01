import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, Navigate, Outlet, useLocation, useParams } from "react-router-dom";

import type { RepoOut } from "../api/types";
import { useRepos } from "../hooks/useRepos";
import { legacyToScoped, repoPath } from "../routes";
import { useAppStore } from "../store";
import { Button } from "../ui";
import viewFrameStyles from "../views/viewFrame.module.css";
import styles from "./RepoScope.module.css";

// Which repo a redirect lands on: the one the store already knows (so a
// legacy link opened mid-session stays on the repo you were looking at),
// else the first registered.
function pickRepo(repos: RepoOut[], storeRepo: string | null): RepoOut | undefined {
  return repos.find((r) => r.name === storeRepo) ?? repos[0];
}

/** The repo list's loading/failure states, shared by every route below so a
 * failed /repos never silently degrades into "no repositories". */
function RepoListStatus({ isPending, isError, error }: { isPending: boolean; isError: boolean; error: unknown }) {
  if (isPending) {
    return <div className={viewFrameStyles.canvasMessage}>Loading repositories…</div>;
  }
  if (isError) {
    return (
      <div className={viewFrameStyles.canvasMessage}>
        Failed to load repositories: {String(error)}
      </div>
    );
  }
  return null;
}

/**
 * Layout route for /repo/:repoUuid. Resolves the uuid against the repo list,
 * writes the repo NAME into the store (every fetcher wants the name), and
 * only then renders the page.
 */
export default function RepoScope() {
  const { repoUuid } = useParams();
  const { repos, isPending, isError, error } = useRepos();
  const storeRepo = useAppStore((state) => state.repo);
  const setRepo = useAppStore((state) => state.setRepo);
  const match = repos.find((r) => r.uuid === repoUuid);
  const name = match?.name ?? null;

  useEffect(() => {
    if (name !== null) setRepo(name);
  }, [name, setRepo]);

  if (isPending || isError) {
    return <RepoListStatus isPending={isPending} isError={isError} error={error} />;
  }
  if (!match) return <RepoNotFound uuid={repoUuid ?? ""} repos={repos} />;
  // The effect above commits after this render, so for one frame the store
  // still holds the previous repo's name. Children fire queries on mount, so
  // rendering them now would send one request scoped to the wrong repo.
  if (storeRepo !== match.name) return null;
  return <Outlet />;
}

function RepoNotFound({ uuid, repos }: { uuid: string; repos: RepoOut[] }) {
  const queryClient = useQueryClient();
  return (
    <div className={viewFrameStyles.canvasMessage}>
      <p className={styles.lead}>
        No repository with id <code className={styles.code}>{uuid}</code>.
      </p>
      {repos.length > 0 && (
        <ul className={styles.list}>
          {repos.map((r) => (
            <li key={r.uuid}>
              <Link to={repoPath(r.uuid)}>{r.name}</Link>
            </li>
          ))}
        </ul>
      )}
      {/* The repo list is cached for the session (staleTime: Infinity), so a
          repo registered after page load is unreachable until a reload —
          give that case a way out that doesn't lose the URL. */}
      <Button
        variant="ghost"
        onClick={() => queryClient.invalidateQueries({ queryKey: ["repos"] })}
      >
        Reload repositories
      </Button>
    </div>
  );
}

/** `/` and any unmatched path: forward to a repo's dashboard. */
export function RootRedirect() {
  const { repos, isPending, isError, error } = useRepos();
  const storeRepo = useAppStore((state) => state.repo);
  if (isPending || isError) {
    return <RepoListStatus isPending={isPending} isError={isError} error={error} />;
  }
  const target = pickRepo(repos, storeRepo);
  // No repos means nowhere to redirect — say so rather than loop.
  if (!target) {
    return (
      <div className={viewFrameStyles.canvasMessage}>
        No repositories registered. Register one with{" "}
        <code className={styles.code}>
          python -m cartograph.ingest register &lt;name&gt; --root /repos/&lt;name&gt;
        </code>
        .
      </div>
    );
  }
  return <Navigate to={repoPath(target.uuid)} replace />;
}

/** Pre-prefix bookmarks (/graph, /kb?sel=3, /c/12 …) → the same page scoped. */
export function LegacyRedirect() {
  const { pathname, search } = useLocation();
  const { repos, isPending, isError, error } = useRepos();
  const storeRepo = useAppStore((state) => state.repo);
  if (isPending || isError) {
    return <RepoListStatus isPending={isPending} isError={isError} error={error} />;
  }
  const target = pickRepo(repos, storeRepo);
  if (!target) return <RootRedirect />;
  return <Navigate to={legacyToScoped(pathname, search, target.uuid)} replace />;
}
