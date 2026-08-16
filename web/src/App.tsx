import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";

import SearchPalette from "./components/SearchPalette";
import SidePanel from "./components/SidePanel";
import TopBar from "./components/TopBar";
import { useAppStore } from "./store";
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

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <RouteSync />
        <SearchPalette />
        <div className="app-shell">
          <TopBar />
          <div className="workspace">
            <main className="canvas-area">
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/c/:communityId" element={<CommunityView />} />
                <Route path="/n/:nodeId" element={<EgoView />} />
              </Routes>
            </main>
            <SidePanel />
          </div>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
