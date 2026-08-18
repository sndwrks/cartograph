import { useEffect } from "react";

import GodNodeList from "./GodNodeList";
import NodeDetail from "./NodeDetail";
import { useAppStore } from "../store";
import styles from "./SidePanel.module.css";

export default function SidePanel() {
  const selectedNodeId = useAppStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);
  const paletteOpen = useAppStore((state) => state.paletteOpen);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Esc deselects — unless the search palette is open (it owns that Esc)
      if (event.key === "Escape" && !paletteOpen) {
        setSelectedNodeId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [paletteOpen, setSelectedNodeId]);

  return (
    <aside className={styles.panel}>
      {selectedNodeId === null ? (
        <GodNodeList />
      ) : (
        <NodeDetail nodeId={selectedNodeId} />
      )}
    </aside>
  );
}
