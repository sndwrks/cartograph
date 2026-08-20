// Typed fetch wrappers over /api/v1 (relative — nginx/Vite proxy routes it).

import type {
  AgentOut,
  Confidence,
  CommunityGraphResponse,
  EgoResponse,
  ImpactResponse,
  KbEntryOut,
  KbStatus,
  KbTypeOut,
  MessageOut,
  NodeDetailResponse,
  NodeOut,
  OverviewResponse,
  RelatedKbTerm,
  SearchResponse,
  ThreadRootOut,
} from "./types";

const BASE = "/api/v1";

/** One entry in FastAPI's 422 `detail` array. */
export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

export class ApiError extends Error {
  status: number;
  /**
   * The parsed error body. FastAPI sends `detail` as a STRING for the errors
   * we raise by hand, but as an ARRAY of {loc, msg} for a 422 validation
   * failure — so `message` alone renders "[object Object]" on exactly the
   * response the KB editor hits most. Callers that care read this.
   */
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }

  /** 422 field errors, keyed by field name, or null for any other shape. */
  fieldErrors(): Record<string, string> | null {
    if (!Array.isArray(this.detail)) return null;
    const out: Record<string, string> = {};
    for (const item of this.detail as FieldError[]) {
      if (!item?.loc) continue;
      out[fieldPath(item.loc)] = item.msg;
    }
    return Object.keys(out).length > 0 ? out : null;
  }
}

// FastAPI's own request validation prefixes `loc` with the scope ("body",
// "query", …), but a `detail` we raise by hand — e.g. a KB payload rejected by
// its type's model — does not. Dropping loc[0] unconditionally turned those
// into a useless "request", so strip it only when it IS a scope.
const LOC_SCOPES = new Set(["body", "query", "path", "header", "cookie"]);

function fieldPath(loc: (string | number)[]): string {
  const parts = LOC_SCOPES.has(String(loc[0])) ? loc.slice(1) : loc;
  return parts.join(".") || "request";
}

type Params = Record<string, string | number | undefined | null>;

function withQuery(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }
  return `${BASE}${path}${query.size > 0 ? `?${query.toString()}` : ""}`;
}

function summarize(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = (detail as FieldError[])
      .filter((item) => item?.msg)
      .map((item) => `${item.loc ? fieldPath(item.loc) : "request"}: ${item.msg}`);
    if (parts.length > 0) return parts.join("; ");
  }
  return fallback;
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(
      response.status,
      summarize(detail, response.statusText),
      detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function get<T>(path: string, params?: Params): Promise<T> {
  return unwrap<T>(await fetch(withQuery(path, params)));
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return unwrap<T>(
    await fetch(`${BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }),
  );
}

const post = <T,>(path: string, body?: unknown) => send<T>("POST", path, body);
const put = <T,>(path: string, body?: unknown) => send<T>("PUT", path, body);
const del = async (path: string): Promise<void> => {
  await unwrap<void>(await fetch(`${BASE}${path}`, { method: "DELETE" }));
};

export const fetchRepos = () => get<{ repos: string[] }>("/repos");

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

export const fetchRelatedKb = (nodeId: number, limit = 5) =>
  get<{ terms: RelatedKbTerm[] }>(`/nodes/${nodeId}/related-kb`, { limit });

// --- knowledge base ---

export interface KbEntryInput {
  type?: string;
  title?: string;
  body?: string;
  slug?: string | null;
  aliases?: string[] | null;
  payload?: Record<string, unknown> | null;
  category?: string | null;
  repository?: string | null;
  status?: "proposed" | "published";
  created_by?: string | null;
}

export const fetchKbTypes = () => get<{ types: KbTypeOut[] }>("/kb/types");

export const fetchKbEntries = (opts?: {
  type?: string;
  status?: KbStatus;
  repo?: string;
  category?: string;
  q?: string;
  limit?: number;
  offset?: number;
}) =>
  get<{ entries: KbEntryOut[]; total: number }>("/kb", {
    type: opts?.type,
    status: opts?.status,
    repo: opts?.repo,
    category: opts?.category,
    q: opts?.q,
    limit: opts?.limit,
    offset: opts?.offset,
  });

export const fetchKbEntry = (entryId: number) =>
  get<KbEntryOut>(`/kb/${entryId}`);

export const createKbEntry = (body: KbEntryInput) =>
  post<KbEntryOut>("/kb", body);

export const updateKbEntry = (entryId: number, body: KbEntryInput) =>
  put<KbEntryOut>(`/kb/${entryId}`, body);

export const deleteKbEntry = (entryId: number) => del(`/kb/${entryId}`);

export const publishKbEntry = (entryId: number, replacesId?: number | null) =>
  post<KbEntryOut>(`/kb/${entryId}/publish`, { replaces_id: replacesId ?? null });

export const rejectKbEntry = (entryId: number, reason: string) =>
  post<KbEntryOut>(`/kb/${entryId}/reject`, { reason });

export const archiveKbEntry = (entryId: number) =>
  post<KbEntryOut>(`/kb/${entryId}/archive`);

export const fetchThreads = (opts?: {
  nodeId?: number;
  agentId?: number;
  repo?: string;
  limit?: number;
}) =>
  get<{ threads: ThreadRootOut[] }>("/messages", {
    node_id: opts?.nodeId,
    agent_id: opts?.agentId,
    repo: opts?.repo,
    limit: opts?.limit,
  });

export const fetchThread = (threadId: number) =>
  get<{ messages: MessageOut[] }>("/messages", { thread_id: threadId });

export const deleteMessage = (messageId: number) => del(`/messages/${messageId}`);

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
