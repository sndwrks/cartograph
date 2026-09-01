import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";

import styles from "./App.module.css";
import RepoScope, { LegacyRedirect, RootRedirect } from "./components/RepoScope";
import SearchPalette from "./components/SearchPalette";
import SidePanel from "./components/SidePanel";
import TopBar from "./components/TopBar";
import { CHILD, LEGACY_ROUTES, REPO_SCOPE, isGraphRoute, parseView } from "./routes";
import { useAppStore } from "./store";
import { TooltipProvider } from "./ui";
import BoardView from "./views/BoardView";
import CommunityView from "./views/CommunityView";
import DashboardView from "./views/DashboardView";
import EgoView from "./views/EgoView";
import KbEditorView from "./views/KbEditorView";
import KbReviewView from "./views/KbReviewView";
import KbView from "./views/KbView";
import Overview from "./views/Overview";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

// Keeps the store's view in sync with the URL so deep links work.
function RouteSync() {
  const { pathname } = useLocation();
  const setView = useAppStore((state) => state.setView);

  useEffect(() => {
    setView(parseView(pathname));
  }, [pathname, setView]);

  return null;
}

function Workspace() {
  const { pathname } = useLocation();
  // The side panel is a fixed sibling of the canvas inside the workspace grid
  // and belongs to the GRAPH routes only — it renders god nodes or node
  // detail, which mean nothing anywhere else. With the panel absent,
  // .workspace's `auto` track just collapses. (The allowlist itself lives in
  // routes.ts next to the other path matchers.)
  const showSidePanel = isGraphRoute(pathname);

  return (
    <div className={styles.workspace}>
      <main className={styles.canvasArea}>
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          {/* Everything is scoped to one repo by URL: RepoScope resolves the
              uuid, writes the name into the store, and renders the page. */}
          <Route path={REPO_SCOPE} element={<RepoScope />}>
            <Route index element={<DashboardView />} />
            <Route path={CHILD.graph} element={<Overview />} />
            <Route path={CHILD.community} element={<CommunityView />} />
            <Route path={CHILD.node} element={<EgoView />} />
            <Route path={CHILD.board} element={<BoardView />} />
            {/* Selection lives in ?sel=, not a path segment: the index and
                the detail share one fetch, and this way it deep-links. */}
            <Route path={CHILD.kb} element={<KbView />} />
            <Route path={CHILD.kbReview} element={<KbReviewView />} />
            <Route path={CHILD.kbNew} element={<KbEditorView />} />
            <Route path={CHILD.kbEdit} element={<KbEditorView />} />
            <Route path="*" element={<RootRedirect />} />
          </Route>
          {/* Bookmarks from before the repo prefix: the old path is exactly
              the scoped suffix, so each just gets prefixed. */}
          {LEGACY_ROUTES.map((root) => (
            <Route key={root} path={`${root}/*`} element={<LegacyRedirect />} />
          ))}
          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </main>
      {showSidePanel && <SidePanel />}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* One provider for the whole tree so every Tooltip shares open/close
          timing — Radix tooltips are inert without an ancestor provider. */}
      <TooltipProvider delayDuration={300}>
        <BrowserRouter>
          <RouteSync />
          <SearchPalette />
          <div className={styles.shell}>
            <TopBar />
            <Workspace />
          </div>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
