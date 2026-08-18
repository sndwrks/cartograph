# Slice 09 — MCP server (query tools)

## Goal

The `mcp` compose service becomes a real MCP server on the official Python SDK: streamable HTTP transport, bearer-token auth, and five tools — `search_code`, `get_node`, `get_neighbors`, `impact_of`, `kb_lookup` — each a thin wrapper over the slice 07/08 query layer. Claude Code on the host can connect and query the graph.

## Depends on

Slices 07 and 08 (query functions). Replaces the slice-01 stub.

## Spec references

`initial-spec.md` §6 (tool list and instructed behaviors), §10 (bearer token: decided yes).

## Requirements

### 1. Server — `cartograph/mcp_server/`

1. Official MCP Python SDK (`mcp` package; add to `pyproject.toml`), `FastMCP` server named `cartograph`, **streamable HTTP** transport bound to `0.0.0.0:8765` (the compose service already publishes 8765 to the host).
2. **Auth:** every HTTP request must carry `Authorization: Bearer <MCP_BEARER_TOKEN>` matching the env value (constant-time compare). Missing/wrong token → 401 before any MCP handling. Implement as ASGI middleware wrapping the SDK's streamable-http app. If `MCP_BEARER_TOKEN` is unset, refuse to start with a clear error.
3. DB access: build the async engine/session from `cartograph.db` exactly as the API does; one session per tool invocation.
4. Server instructions (the MCP `instructions` field) must state: *prefer `kb_lookup` when encountering unfamiliar acronyms or internal terms; treat `name_match` edges as unproven hints, `llm_inferred` as model judgment, `resolved` as proven.*

### 2. Tools

All results JSON-serializable dicts reusing slice-07 schema shapes; **every edge everywhere includes its `confidence` string.** Errors (unknown node/repo) return a structured `{"error": ...}` rather than raising.

1. `search_code(query: str, repo: str | None = None, kinds: list[str] | None = None, limit: int = 10)` → hybrid search (degrades to text until slice 13, same as the API): qualified names, file paths with line spans, kind, summary (may be null until slice 13), score. Description: "Search code entities by name and meaning. Use before guessing at symbol locations."
2. `get_node(qualified_name: str, repo: str | None = None)` → node detail plus its immediate in/out edges with confidence tags (cap 100 edges per direction, counts included). Accepts a qualified name, not an id — assistants think in names; resolve via exact qname match, falling back to unique bare-name match, else return candidates list.
3. `get_neighbors(qualified_name: str, hops: int = 1, limit: int = 50, min_confidence: str | None = None)` → ego query (slice 07 `ego`), nodes + edges.
4. `impact_of(qualified_name: str, direction: str = "upstream", max_depth: int = 5)` → blast radius: depth-annotated list of affected entities. Description: "What breaks if this changes — callers/importers, transitive."
5. `kb_lookup(term: str)` → slice-08 lookup verbatim (exact → alias → none-until-slice-13), returning term, definition, aliases, category, match kind. Description: "Resolve company acronyms and internal terms. ALWAYS call this before assuming what an acronym means."

### 3. Compose

`mcp` service command becomes `uv run python -m cartograph.mcp_server`; healthcheck hits an unauthenticated `/healthz` route in the same ASGI app (the only route exempt from auth).

### 4. Client config docs

Root `README.md` gains a section: connect from host Claude Code with

```
claude mcp add cartograph --transport http http://localhost:8765/mcp \
  --header "Authorization: Bearer $MCP_BEARER_TOKEN"
```

## Files

- `backend/src/cartograph/mcp_server/{__main__.py,server.py,auth.py,tools.py}` (stub replaced)
- `backend/tests/mcp/test_auth.py`, `backend/tests/mcp/test_tools.py`
- `README.md` (connection section), `docker-compose.yml` (mcp command/healthcheck)

## Acceptance criteria

1. `uv run pytest tests/mcp/` passes: tool functions tested directly against the seeded test DB (search finds, get_node resolves by qname and by unique bare name, ambiguous bare name returns candidates, neighbors respects `min_confidence`, impact depths correct, kb_lookup passes the PSN determinism test through MCP); auth middleware unit-tested (no header → 401, wrong token → 401, right token → passes, `/healthz` open).
2. Live: `docker compose up -d`, then from the host use the MCP SDK client (or `claude mcp add` + a manual session) to initialize against `http://localhost:8765/mcp` with the token, list tools (exactly five, with the specified descriptions), and call `search_code` + `get_node` against the ingested fixture repo — real payloads with confidence tags.
3. `curl -X POST http://localhost:8765/mcp` without the header → 401.
4. `docker compose ps` shows mcp healthy via `/healthz`.

## Out of scope

- `post_message` / `read_board` tools and agent self-registration (slice 14).
- OAuth or anything beyond the static bearer token.
- Hybrid/semantic search quality — arrives with slice 13 and flows through automatically.
