// Typed fetch wrappers over /api/v1 (relative — nginx/Vite proxy routes it).

import type {
  AgentOut,
  Confidence,
  CommunityGraphResponse,
  EgoResponse,
  ImpactResponse,
  MessageOut,
  NodeDetailResponse,
  NodeOut,
  OverviewResponse,
  SearchResponse,
  ThreadRootOut,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Params = Record<string, string | number | undefined | null>;

async function get<T>(path: string, params?: Params): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const response = await fetch(`${BASE}${path}${suffix}`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const fetchOverview = (repo: string) =>
  get<OverviewResponse>("/overview", { repo });

export const fetchCommunityGraph = (communityId: number, limit?: number) =>
  get<CommunityGraphResponse>(`/communities/${communityId}/graph`, { limit });

export const fetchNode = (nodeId: number) =>
  get<NodeDetailResponse>(`/nodes/${nodeId}`);

export const fetchEgo = (
  nodeId: number,
  opts?: { hops?: number; limit?: number; minConfidence?: Confidence | null },
) =>
  get<EgoResponse>(`/nodes/${nodeId}/ego`, {
    hops: opts?.hops,
    limit: opts?.limit,
    min_confidence: opts?.minConfidence ?? undefined,
  });

export const fetchImpact = (
  nodeId: number,
  opts?: { direction?: "upstream" | "downstream"; maxDepth?: number },
) =>
  get<ImpactResponse>(`/nodes/${nodeId}/impact`, {
    direction: opts?.direction,
    max_depth: opts?.maxDepth,
  });

export const fetchGodNodes = (
  repo: string,
  opts?: { limit?: number; kind?: string; communityId?: number },
) =>
  get<{ nodes: NodeOut[] }>("/god-nodes", {
    repo,
    limit: opts?.limit,
    kind: opts?.kind,
    community_id: opts?.communityId,
  });

export interface RelatedKbTerm {
  term: string;
  definition: string;
  category: string | null;
  score: number;
}

export const fetchRelatedKb = (nodeId: number, limit = 5) =>
  get<{ terms: RelatedKbTerm[] }>(`/nodes/${nodeId}/related-kb`, { limit });

export const fetchThreads = (nodeId: number) =>
  get<{ threads: ThreadRootOut[] }>("/messages", { node_id: nodeId });

export const fetchThread = (threadId: number) =>
  get<{ messages: MessageOut[] }>("/messages", { thread_id: threadId });

export const fetchAgents = () => get<{ agents: AgentOut[] }>("/agents");

export const searchCode = (
  q: string,
  opts?: { repo?: string; mode?: "text" | "hybrid"; kinds?: string; limit?: number },
) =>
  get<SearchResponse>("/search", {
    q,
    repo: opts?.repo,
    mode: opts?.mode,
    kinds: opts?.kinds,
    limit: opts?.limit,
  });
