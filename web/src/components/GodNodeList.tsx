import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchGodNodes } from "../api/client";
import type { EgoResponse, NodeOut } from "../api/types";
import KindBadge from "./KindBadge";
import { Gear } from "./icons";
import { useAppStore } from "../store";
import {
  Button,
  Input,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  cx,
} from "../ui";
import styles from "./GodNodeList.module.css";

const DEFAULT_CAUTION_THRESHOLD = Number(
  (import.meta.env.VITE_CAUTION_IN_DEGREE as string | undefined) ?? "10",
);

export default function GodNodeList() {
  const repo = useAppStore((state) => state.repo);
  const view = useAppStore((state) => state.view);
  const hopDepth = useAppStore((state) => state.hopDepth);
  const minConfidence = useAppStore((state) => state.minConfidence);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);
  const requestFocus = useAppStore((state) => state.requestFocus);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [threshold, setThreshold] = useState(DEFAULT_CAUTION_THRESHOLD);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // in ego view, keep the last overview/community scope
  const lastScopeRef = useRef<number | undefined>(undefined);
  if (view.mode === "community") lastScopeRef.current = view.id;
  else if (view.mode === "overview") lastScopeRef.current = undefined;
  const communityId = lastScopeRef.current;

  const query = useQuery({
    queryKey: ["god-nodes", repo, communityId ?? null],
    queryFn: () => fetchGodNodes(repo ?? "", { limit: 20, communityId }),
    enabled: repo !== null,
    staleTime: 30_000,
  });

  const nodes = query.data?.nodes ?? [];
  const maxRank = Math.max(...nodes.map((node) => node.pagerank), 1e-9);

  const onRowClick = (node: NodeOut) => {
    setSelectedNodeId(node.id);
    if (view.mode === "community") {
      if (node.community_id === view.id) {
        requestFocus(node.id); // pan + highlight in place
      } else {
        navigate(`/n/${node.id}`);
      }
      return;
    }
    if (view.mode === "ego") {
      const ego = queryClient.getQueryData<EgoResponse>([
        "ego",
        view.nodeId,
        hopDepth,
        minConfidence,
      ]);
      if (ego?.nodes.some((candidate) => candidate.id === node.id)) {
        requestFocus(node.id);
      } else {
        navigate(`/n/${node.id}`);
      }
      return;
    }
    navigate(`/n/${node.id}`);
  };

  return (
    <div>
      <div className={styles.panelHeading}>
        <h2 className={styles.sectionHeading}>
          God nodes
          {communityId !== undefined ? ` · community #${communityId}` : ""}
        </h2>
        <Button
          variant="ghost"
          size="iconSm"
          title="Panel settings"
          className={styles.settingsToggle}
          onClick={() => setSettingsOpen((open) => !open)}
        >
          <Gear />
        </Button>
      </div>
      {settingsOpen && (
        <div className={styles.settingsPanel}>
          <label className={styles.settingsLabel}>
            ⚠ fan-in threshold
            <Input
              type="number"
              min={0}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
              className={styles.thresholdInput}
            />
          </label>
        </div>
      )}
      {query.isPending && <p className="muted">Loading…</p>}
      {query.isError && <p className="muted">Failed: {String(query.error)}</p>}
      {!query.isPending && nodes.length === 0 && (
        <p className="muted">No nodes yet — run ingest and metrics.</p>
      )}
      <ul className={styles.list}>
        {nodes.map((node) => (
          <li
            key={node.id}
            className={styles.row}
            onClick={() => onRowClick(node)}
          >
            <div className={styles.rowTop}>
              <KindBadge kind={node.kind} />
              <span className={styles.name}>{node.name}</span>
              {node.degree_in > threshold && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className={styles.caution}>⚠</span>
                  </TooltipTrigger>
                  <TooltipContent>
                    High fan-in ({node.degree_in} callers) — change carefully
                  </TooltipContent>
                </Tooltip>
              )}
              <span className={cx(styles.degrees, "muted")}>
                ↓{node.degree_in} ↑{node.degree_out}
              </span>
            </div>
            <div className={styles.meter}>
              <span
                className={styles.meterFill}
                style={{ width: `${(node.pagerank / maxRank) * 100}%` }}
              />
            </div>
            <div className={cx(styles.summary, "muted")}>
              {node.summary ?? "no summary yet"}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
