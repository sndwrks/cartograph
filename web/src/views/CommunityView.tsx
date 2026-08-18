import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { fetchCommunityGraph } from "../api/client";
import Breadcrumbs from "../components/Breadcrumbs";
import GraphCanvas, {
  type CanvasLink,
  type CanvasNode,
} from "../components/GraphCanvas";
import { radiusScale, toCanvasLink, toCanvasNode } from "../graphStyle";
import { useAppStore } from "../store";
import { COMMUNITY_COLOR, EDGE_COLOR } from "../theme";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui";
import { useOverviewQuery } from "./Overview";
import viewFrameStyles from "./viewFrame.module.css";

const LIMIT_OPTIONS = [100, 250, 500];

export default function CommunityView() {
  const params = useParams();
  const communityId = Number(params.communityId);
  const navigate = useNavigate();
  const repo = useAppStore((state) => state.repo);
  const selectedNodeId = useAppStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);
  const requestFocus = useAppStore((state) => state.requestFocus);
  const [limit, setLimit] = useState(500);

  const overview = useOverviewQuery(repo);
  const communityLabels = useMemo(() => {
    const labels = new Map<number, string>();
    for (const community of overview.data?.communities ?? []) {
      labels.set(community.id, community.label ?? `community #${community.id}`);
    }
    return labels;
  }, [overview.data]);

  const query = useQuery({
    queryKey: ["community-graph", communityId, limit],
    queryFn: () => fetchCommunityGraph(communityId, limit),
    enabled: Number.isFinite(communityId),
  });

  const graph = useMemo(() => {
    const data = query.data;
    if (!data) return { nodes: [] as CanvasNode[], links: [] as CanvasLink[] };
    const radius = radiusScale(data.nodes);
    const nodes: CanvasNode[] = data.nodes.map((node) =>
      toCanvasNode(node, radius(node)),
    );
    const links: CanvasLink[] = data.edges.map(toCanvasLink);

    // one ghosted phantom marker per neighboring community
    const neighborIds = [...new Set(data.stub_edges.map((s) => s.dst_community_id))];
    for (const neighborId of neighborIds) {
      nodes.push({
        id: `phantom-${neighborId}`,
        label: communityLabels.get(neighborId) ?? `community #${neighborId}`,
        color: COMMUNITY_COLOR,
        radius: 7,
        phantom: true,
        tooltip: `<div class="tooltip">Jump to ${
          communityLabels.get(neighborId) ?? `community #${neighborId}`
        }</div>`,
      });
    }
    for (const stub of data.stub_edges) {
      links.push({
        source: stub.src_id,
        target: `phantom-${stub.dst_community_id}`,
        color: `${EDGE_COLOR}55`, // ghosted
        width: Math.min(1 + Math.log2(stub.weight + 1), 4),
        dash: [3, 3],
      });
    }
    return { nodes, links };
    // selectedNodeId is deliberately not a dep: rebuilding nodes would re-heat
    // the simulation and re-fit the view on every click. GraphCanvas draws the
    // selection ring from its selectedId prop instead.
  }, [query.data, communityLabels]);

  const label = communityLabels.get(communityId) ?? `community #${communityId}`;

  return (
    <div className={viewFrameStyles.viewFrame}>
      <div className={viewFrameStyles.viewToolbar}>
        <Breadcrumbs crumbs={[{ label: "Overview", to: "/graph" }, { label }]} />
        <div className={viewFrameStyles.toolbarControls}>
          <label>
            top
            <Select
              value={String(limit)}
              onValueChange={(value) => setLimit(Number(value))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LIMIT_OPTIONS.map((option) => (
                  <SelectItem key={option} value={String(option)}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>
      </div>
      <div className={viewFrameStyles.viewCanvas}>
        {query.isPending ? (
          <div className={viewFrameStyles.canvasMessage}>Loading community…</div>
        ) : query.isError ? (
          <div className={viewFrameStyles.canvasMessage}>
            Failed to load community: {String(query.error)}
          </div>
        ) : (
          <GraphCanvas
            nodes={graph.nodes}
            links={graph.links}
            selectedId={selectedNodeId}
            onNodeClick={(node) => {
              if (typeof node.id === "string") {
                navigate(`/c/${node.id.replace("phantom-", "")}`);
              } else {
                setSelectedNodeId(node.id);
                requestFocus(node.id);
              }
            }}
          />
        )}
      </div>
    </div>
  );
}
