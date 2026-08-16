import { useEffect } from "react";

import GodNodeList from "./GodNodeList";
import NodeDetail from "./NodeDetail";
import { useAppStore } from "../store";

export default function SidePanel() {
  const selectedNodeId = useAppStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Esc deselects — unless the search palette is open (it owns that Esc)
      if (event.key === "Escape" && !document.querySelector(".palette")) {
        setSelectedNodeId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setSelectedNodeId]);

  return (
    <aside className="side-panel">
      {selectedNodeId === null ? (
        <GodNodeList />
      ) : (
        <NodeDetail nodeId={selectedNodeId} />
      )}
    </aside>
  );
}
