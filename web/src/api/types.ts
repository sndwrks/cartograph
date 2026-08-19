// Response shapes mirroring backend/src/cartograph/api/schemas.py (slice 07/08).

export type Confidence = "resolved" | "llm_inferred" | "name_match";

export type NodeKind =
  | "file"
  | "module"
  | "class"
  | "function"
  | "method"
  | "doc"
  | "config";

export interface NodeOut {
  id: number;
  kind: NodeKind;
  name: string;
  qualified_name: string;
  file_path: string | null;
  start_line: number | null;
  end_line: number | null;
  summary: string | null;
  pagerank: number;
  degree_in: number;
  degree_out: number;
  community_id: number | null;
}

export interface EdgeOut {
  src_id: number;
  dst_id: number;
  rel: string;
  confidence: Confidence;
  src_line: number | null;
}

export interface CommunityOut {
  id: number;
  label: string | null;
  summary: string | null;
  node_count: number;
  internal_edge_count: number;
}

export interface CommunityEdgeOut {
  src_community_id: number;
  dst_community_id: number;
  weight: number;
}

export interface StubEdgeOut {
  src_id: number;
  dst_community_id: number;
  weight: number;
}

export interface ImpactItem {
  node: NodeOut;
  depth: number;
  via: EdgeOut;
}

export interface SearchResult {
  node: NodeOut;
  score: number;
  source: string;
}

export interface OverviewResponse {
  communities: CommunityOut[];
  community_edges: CommunityEdgeOut[];
}

export interface CommunityGraphResponse {
  nodes: NodeOut[];
  edges: EdgeOut[];
  stub_edges: StubEdgeOut[];
}

export interface NodeDetailResponse {
  node: NodeOut;
  edge_counts: {
    in: Record<string, Record<string, number>>;
    out: Record<string, Record<string, number>>;
  };
}

export interface EgoResponse {
  nodes: NodeOut[];
  edges: EdgeOut[];
}

export interface ImpactResponse {
  root_id: number;
  items: ImpactItem[];
}

export interface SearchResponse {
  results: SearchResult[];
  degraded?: boolean;
}

export interface MessageOut {
  id: number;
  agent_id: number;
  thread_id: number | null;
  subject: string | null;
  body: string;
  node_id: number | null;
  created_at: string;
}

export interface ThreadRootOut {
  message: MessageOut;
  reply_count: number;
  last_activity: string;
}

export interface AgentOut {
  id: number;
  name: string;
  role: string | null;
  status: string;
}

// --- knowledge base (slices 15/16) ---

export type KbTypeName =
  | "glossary"
  | "convention"
  | "decision"
  | "specification"
  | "runbook";

export type KbStatus = "proposed" | "published" | "rejected" | "archived";

export interface KbEntryOut {
  id: number;
  type: string; // not KbTypeName: a backend type the SPA doesn't know yet
  slug: string;
  title: string;
  body: string;
  aliases: string[] | null;
  payload: Record<string, unknown>;
  status: KbStatus;
  review_note: string | null;
  seq: number | null;
  repository_id: number | null;
  repository: string | null; // the repo NAME, or null for global
  source: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  // legacy aliases the backend still emits; prefer title/body/type
  term: string;
  definition: string;
  category: string | null;
}

export interface KbTypeOut {
  name: string;
  label: string;
  lookup_keys: string[];
  assigns_seq: boolean;
  export_dir: string | null;
  payload_schema: Record<string, unknown>;
  payload_fields: Record<string, string>;
}

/** A KB entry near a node's embedding. Lives here, not inline in client.ts. */
export interface RelatedKbTerm {
  id: number;
  type: string;
  slug: string;
  title: string;
  body: string;
  term: string;
  definition: string;
  category: string | null;
  score: number;
}
