# Slice 07 — Query layer & graph read API

## Goal

The shared query layer (`cartograph/query/graph.py`, `search.py`) exists with typed functions for every graph read, and FastAPI routers expose them under `/api/v1` in exactly the shapes the SPA will consume. This layer is the single place SQL lives — slice 09's MCP tools call these same functions.

## Depends on

Slice 06 (pagerank/communities populated). Slice 05's data for tests.

## Spec references

`initial-spec.md` §5 (API surface — endpoint list and semantics), §7 (payload-size rules: client never receives more than ~2,500 renderable nodes).

## Requirements

### 1. Shared response shapes — `api/schemas.py`

Pydantic models used by both the API and (slice 09) MCP serialization:

```
NodeOut: id, kind, name, qualified_name, file_path, start_line, end_line,
         summary, pagerank, degree_in, degree_out, community_id
EdgeOut: src_id, dst_id, rel, confidence, src_line
CommunityOut: id, label, summary, node_count, internal_edge_count
CommunityEdgeOut: src_community_id, dst_community_id, weight
```

`confidence` is always serialized as its string value — never omitted.

### 2. Query functions — `cartograph/query/graph.py`

All async, all taking an `AsyncSession`, all repo-scoped where applicable:

1. `overview(repo_name)` → all communities (CommunityOut) + all community edges. No node data. This is the entire overview payload.
2. `community_graph(community_id, limit=500)` → the community's top-`limit` nodes by pagerank (hard cap 2500) + intra-community edges among the returned nodes + **stub edges**: for edges from a returned node to a node in another community, return `{src_id, dst_community_id, weight}` aggregated per (src, neighbor community). Excludes `file` nodes and `contains` edges.
3. `node_detail(node_id)` → NodeOut + `edge_counts`: `{rel: {confidence: count}}` for in and out separately.
4. `ego(node_id, hops=1, limit=200, min_confidence=None)` → BFS over edges (both directions) up to `hops` (max 3), collecting nodes until `limit` (hard cap 2500), plus all edges among collected nodes. `min_confidence` filters traversed edges by trust order `resolved > llm_inferred > name_match` (e.g. `min_confidence=llm_inferred` excludes `name_match`). `contains` edges excluded.
5. `impact(node_id, direction="upstream", max_depth=5, limit=500)` → recursive CTE. `upstream`: follow edges arriving at the node backwards (who calls/imports/references me, transitively — the blast radius). `downstream`: what the node reaches. Returns a depth-annotated tree: `[{node: NodeOut, depth: int, via: EdgeOut}]`, deduped shortest-depth-first, capped at `limit`.
6. `god_nodes(repo_name, limit=20, kind=None, community_id=None)` → nodes ordered pagerank DESC, `degree_in + degree_out` DESC as tiebreak, optional kind and community filters. Excludes `file` nodes.

### 3. Search — `cartograph/query/search.py`

1. `search_text(repo_name|None, q, kinds=None, limit=20)` → trigram: `GREATEST(similarity(name, :q), similarity(qualified_name, :q))` as score, `WHERE name % :q OR qualified_name % :q`, ordered by score. Returns `[{node: NodeOut, score: float, source: "text"}]`.
2. `search_semantic(...)` and `search_hybrid(...)`: **define the signatures and the RRF merge now; implement semantic as raising `NotImplementedError` until slice 13.** The RRF function is pure and implemented+tested in this slice: given two ranked lists of node ids, score each id `Σ 1/(60 + rank_i)` and merge descending.

### 4. Routers — `api/routers/graph.py`, `api/routers/search.py`

Thin: parse/validate query params, call the query function, return the schema. Endpoints (all under `/api/v1`):

```
GET /overview?repo=NAME                                   → {communities: [...], community_edges: [...]}
GET /communities/{id}/graph?limit=500                      → {nodes: [...], edges: [...], stub_edges: [...]}
GET /nodes/{id}                                            → {node: {...}, edge_counts: {in: {...}, out: {...}}}
GET /nodes/{id}/ego?hops=1&limit=200&min_confidence=       → {nodes: [...], edges: [...]}
GET /nodes/{id}/impact?direction=upstream&max_depth=5      → {root_id, items: [{node, depth, via}]}
GET /god-nodes?repo=NAME&limit=20&kind=&community_id=      → {nodes: [...]}
GET /search?q=&repo=&mode=hybrid&kinds=&limit=20           → {results: [{node, score, source}]}
```

Semantics: `mode` defaults to `hybrid`; until slice 13, `hybrid` **degrades to text with a `"degraded": true` field in the response** (the SPA ships against `hybrid` from day one), and `mode=semantic` returns HTTP 501. Unknown repo → 404. Validation errors → 422 (FastAPI default).

### 5. Wiring

`create_app()` mounts the routers; the ingest-runs and KB/agent routers arrive in slice 08 — leave clean mounting points.

## Files

- `backend/src/cartograph/query/{graph.py,search.py}`
- `backend/src/cartograph/api/{schemas.py}`, `backend/src/cartograph/api/routers/{__init__.py,graph.py,search.py}`
- `backend/tests/api/{conftest.py,test_graph_endpoints.py,test_search.py}` — conftest seeds a small deterministic graph (2 communities, ~12 nodes, edges of all three confidences) directly through the models, then runs endpoint tests with httpx `ASGITransport`

## Acceptance criteria

1. `uv run pytest tests/api/` passes, covering: overview returns only communities+community-edges; community graph truncates at `limit` by pagerank and returns correct stub edges; ego at hops=1 vs hops=2 returns strictly growing node sets and respects `min_confidence` (a `name_match`-only path disappears when filtered); impact upstream on a leaf returns its transitive callers with correct depths and never loops on a cycle (seed one cycle); god-nodes ordering (equal-pagerank tiebreak by degree); text search finds a node by fuzzy fragment (`"ordr"` → `OrderService`) with kind filter; `mode=semantic` → 501; `mode=hybrid` → text results + `degraded: true`; every edge in every payload has a `confidence` string.
2. RRF unit test: two hand-built rankings merge in the expected order.
3. Live check against ingested `py_sample`: `curl "localhost:8000/api/v1/overview?repo=py_sample"` and `curl "localhost:8000/api/v1/god-nodes?repo=py_sample"` return plausible non-empty payloads.

## Out of scope

- KB, agents, messages, ingest-runs endpoints (slice 08).
- Real semantic/hybrid search (slice 13 implements `search_semantic` and flips `hybrid`).
- Any caching layer — these are indexed reads by design.
