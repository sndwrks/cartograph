"""MCP server assembly: MCPServer + tools + bearer auth + /healthz (slice 09)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from cartograph.config import get_settings
from cartograph.db import get_sessionmaker
from cartograph.mcp_server import tools
from cartograph.mcp_server.auth import BearerAuthMiddleware

INSTRUCTIONS = (
    "Cartograph exposes a persistent knowledge graph of one or more code "
    "repositories: files, modules, classes, functions and their imports, "
    "calls, inheritance and references. Prefer kb_lookup when encountering "
    "unfamiliar acronyms or internal terms. Every edge carries a confidence "
    "tag — treat name_match edges as unproven hints, llm_inferred as model "
    "judgment, and resolved as proven."
)


def build_mcp_server() -> MCPServer:
    server = MCPServer("cartograph", instructions=INSTRUCTIONS)
    sessionmaker = get_sessionmaker()

    @server.tool(
        description=(
            "Search code entities by name and meaning. "
            "Use before guessing at symbol locations."
        )
    )
    async def search_code(
        query: str,
        repo: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 10,
    ) -> dict:
        async with sessionmaker() as session:
            return await tools.search_code(session, query, repo, kinds, limit)

    @server.tool(
        description=(
            "Get a code entity by qualified name (bare names resolve when "
            "unique): detail, metrics, and its immediate in/out edges with "
            "confidence tags."
        )
    )
    async def get_node(qualified_name: str, repo: str | None = None) -> dict:
        async with sessionmaker() as session:
            return await tools.get_node(session, qualified_name, repo)

    @server.tool(
        description=(
            "Neighborhood of a code entity: nodes and edges within N hops, "
            "optionally filtered by minimum edge confidence "
            "(resolved > llm_inferred > name_match)."
        )
    )
    async def get_neighbors(
        qualified_name: str,
        hops: int = 1,
        limit: int = 50,
        min_confidence: str | None = None,
    ) -> dict:
        async with sessionmaker() as session:
            return await tools.get_neighbors(
                session, qualified_name, hops, limit, min_confidence
            )

    @server.tool(
        description=(
            "What breaks if this changes — callers/importers, transitive. "
            "Depth-annotated blast radius, upstream or downstream."
        )
    )
    async def impact_of(
        qualified_name: str, direction: str = "upstream", max_depth: int = 5
    ) -> dict:
        async with sessionmaker() as session:
            return await tools.impact_of(session, qualified_name, direction, max_depth)

    @server.tool(
        description=(
            "Resolve company acronyms and internal terms. ALWAYS call this "
            "before assuming what an acronym means."
        )
    )
    async def kb_lookup(term: str) -> dict:
        async with sessionmaker() as session:
            return await tools.kb_lookup(session, term)

    @server.tool(
        description=(
            "Post to the agent coordination board. Anchor to a symbol with "
            "node_qualified_name when the message is about specific code. "
            "First post from a new agent_name self-registers the agent."
        )
    )
    async def post_message(
        agent_name: str,
        body: str,
        subject: str | None = None,
        thread_id: int | None = None,
        node_qualified_name: str | None = None,
    ) -> dict:
        async with sessionmaker() as session:
            return await tools.post_message(
                session, agent_name, body, subject, thread_id, node_qualified_name
            )

    @server.tool(
        description=(
            "Read the agent coordination board. Check for existing threads "
            "about a symbol before starting work on it. Without thread_id: "
            "thread roots newest-first; with thread_id: the full thread."
        )
    )
    async def read_board(
        limit: int = 20,
        thread_id: int | None = None,
        node_qualified_name: str | None = None,
        agent_name: str | None = None,
        since: str | None = None,
    ) -> dict:
        async with sessionmaker() as session:
            return await tools.read_board(
                session, limit, thread_id, node_qualified_name, agent_name, since
            )

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return server


def build_app(token: str | None = None):
    """The full ASGI app: streamable-HTTP MCP wrapped in bearer auth."""
    if token is None:
        token = get_settings().MCP_BEARER_TOKEN
    server = build_mcp_server()
    app = server.streamable_http_app(stateless_http=True, host="0.0.0.0")
    return BearerAuthMiddleware(app, token)
