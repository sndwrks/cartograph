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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui";
import { useOverviewQuery } from "./Overview";
import viewFrameStyles from "./viewFrame.module.css";

const HOP_OPTIONS = [1, 2, 3];

const CONFIDENCE_OPTIONS: { label: string; value: Confidence | null }[] = [
  { label: "All", value: null },
  { label: "≥ llm_inferred", value: "llm_inferred" },
  { label: "resolved only", value: "resolved" },
];

// Radix Select.Item rejects an empty-string value (reserved to mean "no
// selection"), so the "All" / null option round-trips through this sentinel
// instead of "".
const ANY_CONFIDENCE_VALUE = "any";

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
  const crumbs: Crumb[] = [{ label: "Overview", to: "/graph" }];
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
    <div className={viewFrameStyles.viewFrame}>
      <div className={viewFrameStyles.viewToolbar}>
        <Breadcrumbs crumbs={crumbs} />
        <div className={viewFrameStyles.toolbarControls}>
          <label>
            hops
            <Select
              value={String(hopDepth)}
              onValueChange={(value) => setHopDepth(Number(value))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOP_OPTIONS.map((option) => (
                  <SelectItem key={option} value={String(option)}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <label>
            confidence
            <Select
              value={minConfidence ?? ANY_CONFIDENCE_VALUE}
              onValueChange={(value) =>
                setMinConfidence(
                  value === ANY_CONFIDENCE_VALUE ? null : (value as Confidence),
                )
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONFIDENCE_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.label}
                    value={option.value ?? ANY_CONFIDENCE_VALUE}
                  >
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>
      </div>
      <div className={viewFrameStyles.viewCanvas}>
        {query.isPending ? (
          <div className={viewFrameStyles.canvasMessage}>Loading ego graph…</div>
        ) : query.isError ? (
          <div className={viewFrameStyles.canvasMessage}>
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
