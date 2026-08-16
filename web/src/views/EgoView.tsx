import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useParams } from "react-router-dom";

import { fetchEgo } from "../api/client";
import type { Confidence } from "../api/types";
import Breadcrumbs, { type Crumb } from "../components/Breadcrumbs";
import GraphCanvas, {
  type CanvasLink,
  type CanvasNode,
} from "../components/GraphCanvas";
import {
  communityHalo,
  radiusScale,
  toCanvasLink,
  toCanvasNode,
} from "../graphStyle";
import { useAppStore } from "../store";
import { useOverviewQuery } from "./Overview";

const HOP_OPTIONS = [1, 2, 3];

const CONFIDENCE_OPTIONS: { label: string; value: Confidence | null }[] = [
  { label: "All", value: null },
  { label: "≥ llm_inferred", value: "llm_inferred" },
  { label: "resolved only", value: "resolved" },
];

export default function EgoView() {
  const params = useParams();
  const nodeId = Number(params.nodeId);
  const repo = useAppStore((state) => state.repo);
  const hopDepth = useAppStore((state) => state.hopDepth);
  const setHopDepth = useAppStore((state) => state.setHopDepth);
  const minConfidence = useAppStore((state) => state.minConfidence);
  const setMinConfidence = useAppStore((state) => state.setMinConfidence);
  const selectedNodeId = useAppStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);

  const overview = useOverviewQuery(repo);

  const query = useQuery({
    queryKey: ["ego", nodeId, hopDepth, minConfidence],
    queryFn: () => fetchEgo(nodeId, { hops: hopDepth, minConfidence }),
    enabled: Number.isFinite(nodeId),
  });

  const graph = useMemo(() => {
    const data = query.data;
    if (!data) return { nodes: [] as CanvasNode[], links: [] as CanvasLink[] };
    const radius = radiusScale(data.nodes);
    const nodes = data.nodes.map((node) =>
      toCanvasNode(node, radius(node), {
        ring: node.id === nodeId, // the ego center; route-derived, so stable
        haloColor: communityHalo(node.community_id),
      }),
    );
    const links = data.edges.map(toCanvasLink);
    return { nodes, links };
    // selectedNodeId is deliberately not a dep: rebuilding nodes would re-heat
    // the simulation and re-fit the view on every click. GraphCanvas draws the
    // selection ring from its selectedId prop instead.
  }, [query.data, nodeId]);

  const center = query.data?.nodes.find((node) => node.id === nodeId);
  const crumbs: Crumb[] = [{ label: "Overview", to: "/" }];
  if (center?.community_id != null) {
    const community = overview.data?.communities.find(
      (c) => c.id === center.community_id,
    );
    crumbs.push({
      label: community?.label ?? `community #${center.community_id}`,
      to: `/c/${center.community_id}`,
    });
  }
  crumbs.push({ label: center?.name ?? `node #${nodeId}` });

  return (
    <div className="view-frame">
      <div className="view-toolbar">
        <Breadcrumbs crumbs={crumbs} />
        <div className="toolbar-controls">
          <label>
            hops
            <select
              value={hopDepth}
              onChange={(event) => setHopDepth(Number(event.target.value))}
            >
              {HOP_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            confidence
            <select
              value={minConfidence ?? ""}
              onChange={(event) =>
                setMinConfidence(
                  (event.target.value || null) as Confidence | null,
                )
              }
            >
              {CONFIDENCE_OPTIONS.map((option) => (
                <option key={option.label} value={option.value ?? ""}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="view-canvas">
        {query.isPending ? (
          <div className="canvas-message">Loading ego graph…</div>
        ) : query.isError ? (
          <div className="canvas-message">
            Failed to load ego graph: {String(query.error)}
          </div>
        ) : (
          <GraphCanvas
            nodes={graph.nodes}
            links={graph.links}
            selectedId={selectedNodeId}
            onNodeClick={(node) => {
              if (typeof node.id === "number") setSelectedNodeId(node.id);
            }}
          />
        )}
      </div>
    </div>
  );
}
