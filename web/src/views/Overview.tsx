import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, fetchOverview } from "../api/client";
import GraphCanvas, {
  type CanvasLink,
  type CanvasNode,
} from "../components/GraphCanvas";
import { useAppStore } from "../store";
import { COMMUNITY_COLOR, EDGE_COLOR } from "../theme";
import styles from "./Overview.module.css";
import viewFrameStyles from "./viewFrame.module.css";

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const escapeHtml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function useOverviewQuery(repo: string | null) {
  return useQuery({
    queryKey: ["overview", repo],
    queryFn: () => fetchOverview(repo ?? ""),
    enabled: repo !== null,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
}

export default function Overview() {
  const repo = useAppStore((state) => state.repo);
  const navigate = useNavigate();
  const query = useOverviewQuery(repo);

  const graph = useMemo(() => {
    const nodes: CanvasNode[] = (query.data?.communities ?? []).map(
      (community) => {
        const label = community.label ?? `community #${community.id}`;
        return {
          id: community.id,
          label,
          color: `${COMMUNITY_COLOR}55`,
          radius: clamp(4 * Math.sqrt(community.node_count), 8, 42),
          tooltip: `<div class="tooltip"><strong>${escapeHtml(label)}</strong><br/>${escapeHtml(
            community.summary ?? "no summary yet",
          )}<br/><span class="muted">${community.node_count} nodes · ${community.internal_edge_count} internal edges</span></div>`,
        };
      },
    );
    const links: CanvasLink[] = (query.data?.community_edges ?? []).map(
      (edge) => ({
        source: edge.src_community_id,
        target: edge.dst_community_id,
        color: EDGE_COLOR,
        width: clamp(1 + Math.log2(edge.weight + 1), 1, 8),
        dash: [],
      }),
    );
    return { nodes, links };
  }, [query.data]);

  if (repo === null) {
    return (
      <div className={viewFrameStyles.canvasMessage}>
        Pick a repository to explore.
      </div>
    );
  }
  if (query.isPending) {
    return (
      <div className={viewFrameStyles.canvasMessage}>Loading overview…</div>
    );
  }
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return (
        <EmptyState repo={repo} title={`Repository "${repo}" is not registered.`} />
      );
    }
    return (
      <div className={viewFrameStyles.canvasMessage}>
        Failed to load overview: {String(query.error)}
      </div>
    );
  }
  if (graph.nodes.length === 0) {
    return <EmptyState repo={repo} title={`"${repo}" has no communities yet.`} />;
  }

  return (
    <GraphCanvas
      nodes={graph.nodes}
      links={graph.links}
      onNodeClick={(node) => navigate(`/c/${node.id}`)}
    />
  );
}

function EmptyState({ repo, title }: { repo: string; title: string }) {
  return (
    <div className={viewFrameStyles.canvasMessage}>
      <h2 className={styles.emptyStateHeading}>{title}</h2>
      <p>Ingest the repository and compute metrics, then reload:</p>
      <pre className={styles.emptyStatePre}>
        {`docker compose run -v /host/path/${repo}:/repos/${repo} --rm api \\
  uv run python -m cartograph.ingest run --repo ${repo}
docker compose run --rm api \\
  uv run python -m cartograph.metrics --repo ${repo}`}
      </pre>
    </div>
  );
}
