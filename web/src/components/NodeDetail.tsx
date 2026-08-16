import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { fetchEgo, fetchNode, fetchRelatedKb } from "../api/client";
import type { Confidence, EgoResponse } from "../api/types";
import ConfidenceBadge from "./ConfidenceBadge";
import KindBadge from "./KindBadge";
import ThreadList from "./ThreadList";
import { useAppStore } from "../store";
import { useOverviewQuery } from "../views/Overview";

interface EdgeRow {
  otherId: number;
  otherName: string;
  confidence: Confidence;
  line: number | null;
}

type Groups = Map<string, EdgeRow[]>;

function groupEdges(nodeId: number, ego: EgoResponse | undefined) {
  const outgoing: Groups = new Map();
  const incoming: Groups = new Map();
  if (!ego) return { outgoing, incoming };
  const names = new Map(ego.nodes.map((node) => [node.id, node.name]));
  for (const edge of ego.edges) {
    const isOut = edge.src_id === nodeId;
    const isIn = edge.dst_id === nodeId;
    if (!isOut && !isIn) continue;
    const otherId = isOut ? edge.dst_id : edge.src_id;
    const groups = isOut ? outgoing : incoming;
    const rows = groups.get(edge.rel) ?? [];
    rows.push({
      otherId,
      otherName: names.get(otherId) ?? `#${otherId}`,
      confidence: edge.confidence,
      line: edge.src_line,
    });
    groups.set(edge.rel, rows);
  }
  return { outgoing, incoming };
}

export default function NodeDetail({ nodeId }: { nodeId: number }) {
  const repo = useAppStore((state) => state.repo);
  const setSelectedNodeId = useAppStore((state) => state.setSelectedNodeId);
  const requestFocus = useAppStore((state) => state.requestFocus);
  const navigate = useNavigate();
  const overview = useOverviewQuery(repo);

  const detail = useQuery({
    queryKey: ["node-detail", nodeId],
    queryFn: () => fetchNode(nodeId),
    staleTime: 30_000,
  });
  const ego = useQuery({
    queryKey: ["node-edges", nodeId],
    queryFn: () => fetchEgo(nodeId, { hops: 1, limit: 200 }),
    staleTime: 30_000,
  });
  const relatedKb = useQuery({
    queryKey: ["related-kb", nodeId],
    queryFn: () => fetchRelatedKb(nodeId),
    staleTime: 30_000,
  });

  const groups = useMemo(
    () => groupEdges(nodeId, ego.data),
    [nodeId, ego.data],
  );

  if (detail.isPending) {
    return <p className="muted">Loading node…</p>;
  }
  if (detail.isError) {
    return <p className="muted">Failed to load node: {String(detail.error)}</p>;
  }

  const node = detail.data.node;
  const community = overview.data?.communities.find(
    (candidate) => candidate.id === node.community_id,
  );
  const location =
    node.file_path !== null
      ? `${node.file_path}${
          node.start_line !== null ? `:${node.start_line}–${node.end_line}` : ""
        }`
      : null;

  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text);
  };

  const selectNeighbor = (otherId: number) => {
    setSelectedNodeId(otherId);
    requestFocus(otherId);
  };

  const renderGroups = (groups: Groups, direction: "out" | "in") =>
    [...groups.entries()].map(([rel, rows]) => (
      <details key={`${direction}-${rel}`} open>
        <summary>
          {direction === "out" ? "→" : "←"} {rel}
          <span className="muted"> ({rows.length})</span>
        </summary>
        <ul className="edge-rows">
          {rows.map((row, index) => (
            <li key={`${row.otherId}-${index}`}>
              <button
                type="button"
                className="link-button"
                onClick={() => selectNeighbor(row.otherId)}
              >
                {row.otherName}
              </button>
              {row.line !== null && (
                <span className="muted">:{row.line}</span>
              )}
              <ConfidenceBadge confidence={row.confidence} />
            </li>
          ))}
        </ul>
      </details>
    ));

  return (
    <div className="node-detail">
      <div className="detail-header">
        <KindBadge kind={node.kind} />
        <strong className="detail-name">{node.name}</strong>
        <button
          type="button"
          className="icon-button"
          title="Back to god-node list"
          onClick={() => setSelectedNodeId(null)}
        >
          ✕
        </button>
      </div>
      <button
        type="button"
        className="qname"
        title="Copy qualified name"
        onClick={() => copy(node.qualified_name)}
      >
        {node.qualified_name}
      </button>

      <section>
        <h3>Summary</h3>
        <p className={node.summary ? "" : "muted"}>
          {node.summary ?? "not yet summarized"}
        </p>
      </section>

      {location !== null && (
        <section>
          <h3>Location</h3>
          <button
            type="button"
            className="location"
            title="Copy location"
            onClick={() => copy(location)}
          >
            {location}
          </button>
        </section>
      )}

      <section>
        <h3>Metrics</h3>
        <dl className="metrics">
          <dt>pagerank</dt>
          <dd>{node.pagerank.toFixed(4)}</dd>
          <dt>degree</dt>
          <dd>
            ↓{node.degree_in} ↑{node.degree_out}
          </dd>
          <dt>community</dt>
          <dd>
            {node.community_id !== null ? (
              <button
                type="button"
                className="link-button"
                onClick={() => navigate(`/c/${node.community_id}`)}
              >
                {community?.label ?? `community #${node.community_id}`}
              </button>
            ) : (
              <span className="muted">none</span>
            )}
          </dd>
        </dl>
      </section>

      <section>
        <h3>Edges</h3>
        {ego.isPending && <p className="muted">Loading edges…</p>}
        {renderGroups(groups.outgoing, "out")}
        {renderGroups(groups.incoming, "in")}
        {!ego.isPending &&
          groups.outgoing.size === 0 &&
          groups.incoming.size === 0 && (
            <p className="muted">No non-contains edges.</p>
          )}
      </section>

      <section>
        <h3>Related KB terms</h3>
        {relatedKb.data && relatedKb.data.terms.length > 0 ? (
          <ul className="kb-terms">
            {relatedKb.data.terms.map((term) => (
              <li key={term.term} title={term.definition}>
                <strong>{term.term}</strong>
                <span className="muted"> — {term.definition}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {relatedKb.isPending
              ? "Loading…"
              : "no related terms yet (requires enrichment)"}
          </p>
        )}
      </section>

      <section>
        <h3>Discussion</h3>
        <ThreadList nodeId={node.id} />
      </section>

      <button
        type="button"
        className="action-button expand-button"
        onClick={() => navigate(`/n/${node.id}`)}
      >
        Expand ego graph
      </button>
    </div>
  );
}
