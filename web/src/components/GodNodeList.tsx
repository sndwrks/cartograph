import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchGodNodes } from "../api/client";
import type { EgoResponse, NodeOut } from "../api/types";
import KindBadge from "./KindBadge";
import { useAppStore } from "../store";

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
    <div className="god-node-list">
      <div className="panel-heading">
        <h2>
          God nodes
          {communityId !== undefined ? ` · community #${communityId}` : ""}
        </h2>
        <button
          type="button"
          className="icon-button"
          title="Panel settings"
          onClick={() => setSettingsOpen((open) => !open)}
        >
          ⚙
        </button>
      </div>
      {settingsOpen && (
        <div className="panel-settings">
          <label>
            ⚠ fan-in threshold
            <input
              type="number"
              min={0}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
            />
          </label>
        </div>
      )}
      {query.isPending && <p className="muted">Loading…</p>}
      {query.isError && <p className="muted">Failed: {String(query.error)}</p>}
      {!query.isPending && nodes.length === 0 && (
        <p className="muted">No nodes yet — run ingest and metrics.</p>
      )}
      <ul>
        {nodes.map((node) => (
          <li key={node.id} onClick={() => onRowClick(node)}>
            <div className="god-row-top">
              <KindBadge kind={node.kind} />
              <span className="god-name">{node.name}</span>
              {node.degree_in > threshold && (
                <span
                  className="caution"
                  title="High fan-in — change carefully"
                >
                  ⚠
                </span>
              )}
              <span className="god-degrees muted">
                ↓{node.degree_in} ↑{node.degree_out}
              </span>
            </div>
            <div className="importance-meter">
              <span
                className="importance-fill"
                style={{ width: `${(node.pagerank / maxRank) * 100}%` }}
              />
            </div>
            <div className="god-summary muted">
              {node.summary ?? "no summary yet"}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
