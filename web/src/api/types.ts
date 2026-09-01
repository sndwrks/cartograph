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

// --- repositories ---

export interface RepoOut {
  id: number;
  /** Stable public identifier — the URL segment in /repo/<uuid>/… */
  uuid: string;
  /** The name every other endpoint's `repo=` parameter speaks. */
  name: string;
}

// --- ingest runs (slice 08) ---

export interface IngestRunOut {
  id: number;
  repository: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown> | null;
  // omitted by the list endpoint; GET /ingest/runs/{id} includes it
  error?: string | null;
}

// --- MCP tool usage (usage dashboard) ---

export type UsageWindow = "24h" | "7d" | "30d" | "all";

export interface UsageTotals {
  calls: number;
  errors: number;
  /** calls that named no repo — they show under every repo's dashboard */
  unscoped_calls: number;
  agents: number;
  response_bytes: number;
  request_bytes: number;
  /** calls that have a file baseline (graph tools); the ratio is over these */
  baseline_calls: number;
  baseline_bytes: number;
  /** response bytes of the baseline calls only — like for like */
  baseline_response_bytes: number;
  baseline_files: number;
  est_tokens_returned: number;
  est_tokens_baseline: number;
  est_tokens_saved: number;
  /** saved ÷ baseline over baseline calls; null when there are none */
  savings_ratio: number | null;
}

export interface UsageToolRow {
  tool: string;
  calls: number;
  errors: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  response_bytes: number;
  baseline_bytes: number;
}

export interface UsageBucketRow {
  start: string;
  calls: number;
  errors: number;
  response_bytes: number;
  baseline_bytes: number;
  /** response bytes over the calls that have a baseline — pair with baseline_bytes */
  baseline_response_bytes: number;
}

export interface UsageAgentRow {
  name: string;
  calls: number;
  errors: number;
  last_call: string;
}

export interface UsageSummaryResponse {
  window: UsageWindow;
  bucket: "hour" | "day";
  chars_per_token: number;
  totals: UsageTotals;
  by_tool: UsageToolRow[];
  buckets: UsageBucketRow[];
  agents: UsageAgentRow[];
}

export interface UsageCallOut {
  id: number;
  tool: string;
  repository: string | null;
  repo_arg: string | null;
  agent_name: string | null;
  client_session: string | null;
  arguments: Record<string, unknown>;
  request_bytes: number;
  started_at: string;
  duration_ms: number;
  ok: boolean;
  error_kind: string | null;
  error: string | null;
  response_bytes: number;
  baseline_bytes: number | null;
  baseline_files: number | null;
  result_meta: Record<string, unknown> | null;
}
