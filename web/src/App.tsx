import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import styles from "./App.module.css";
import SearchPalette from "./components/SearchPalette";
import SidePanel from "./components/SidePanel";
import TopBar from "./components/TopBar";
import { useAppStore } from "./store";
import { TooltipProvider } from "./ui";
import BoardView from "./views/BoardView";
import CommunityView from "./views/CommunityView";
import EgoView from "./views/EgoView";
import Overview from "./views/Overview";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

// Keeps the store's view in sync with the URL so deep links work.
function RouteSync() {
  const { pathname } = useLocation();
  const setView = useAppStore((state) => state.setView);

  useEffect(() => {
    const community = pathname.match(/^\/c\/(\d+)$/);
    const node = pathname.match(/^\/n\/(\d+)$/);
    if (community) {
      setView({ mode: "community", id: Number(community[1]) });
    } else if (node) {
      setView({ mode: "ego", nodeId: Number(node[1]) });
    } else {
      setView({ mode: "overview" });
    }
  }, [pathname, setView]);

  return null;
}

// The side panel is a fixed sibling of the canvas inside the workspace grid,
// used only by the graph routes (it shows god nodes / node detail). The
// board is a full-width page, so it's gated out on that route rather than
// rendered empty — with it absent, .workspace's `auto` track just collapses.
function Workspace() {
  const { pathname } = useLocation();
  const showSidePanel = pathname !== "/board";

  return (
    <div className={styles.workspace}>
      <main className={styles.canvasArea}>
        <Routes>
          {/* The graph lives at /graph so every section has a real name and
              the tab strip has something to match; / just forwards to it. */}
          <Route path="/" element={<Navigate to="/graph" replace />} />
          <Route path="/graph" element={<Overview />} />
          <Route path="/c/:communityId" element={<CommunityView />} />
          <Route path="/n/:nodeId" element={<EgoView />} />
          <Route path="/board" element={<BoardView />} />
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
