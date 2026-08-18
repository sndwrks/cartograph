"""MCP tool implementations: thin wrappers over the query layer (slice 09).

Each function takes an AsyncSession so tests can drive them directly; the
server registers session-opening wrappers. All results are JSON-serializable
dicts reusing the slice-07 schema shapes — every edge carries its confidence
string. Errors return {"error": ...} rather than raising.
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Agent, AgentMessage, Edge, Node, NodeKind, Repository
from cartograph.query import graph as q_graph
from cartograph.query import kb as q_kb
from cartograph.query import messages as q_messages
from cartograph.query import search as q_search
from cartograph.query.agents import get_or_create_agent

EDGE_CAP = 100  # per direction, in get_node
CANDIDATE_CAP = 10


async def _resolve_node(
    session: AsyncSession, qualified_name: str, repo: str | None = None
) -> tuple[Node | None, dict | None]:
    """Resolve a qualified name to a node: exact qname, else unique bare name.

    Returns (node, None) on success, (None, error_dict) otherwise — including
    a candidates list when the name is ambiguous.
    """
    repo_id = None
    if repo is not None:
        repository = await session.scalar(
            select(Repository).where(Repository.name == repo)
        )
        if repository is None:
            return None, {"error": f"unknown repository {repo!r}"}
        repo_id = repository.id

    def scoped(stmt):
        stmt = stmt.where(Node.kind != NodeKind.file)
        if repo_id is not None:
            stmt = stmt.where(Node.repository_id == repo_id)
        return stmt

    exact = list(
        (
            await session.scalars(
                scoped(select(Node).where(Node.qualified_name == qualified_name))
                .order_by(Node.id)
                .limit(CANDIDATE_CAP + 1)
            )
        ).all()
    )
    matches = exact
    if not matches:
        matches = list(
            (
                await session.scalars(
                    scoped(select(Node).where(Node.name == qualified_name))
                    .order_by(Node.pagerank.desc(), Node.id)
                    .limit(CANDIDATE_CAP + 1)
                )
            ).all()
        )
    if not matches:
        return None, {"error": f"no node found for {qualified_name!r}"}
    if len(matches) > 1:
        return None, {
            "error": f"ambiguous name {qualified_name!r} — pass a qualified name",
            "candidates": [
                {
                    "qualified_name": n.qualified_name,
                    "kind": n.kind.value,
                    "file_path": n.file_path,
                }
                for n in matches[:CANDIDATE_CAP]
            ],
        }
    return matches[0], None


async def search_code(
    session: AsyncSession,
    query: str,
    repo: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 10,
) -> dict:
    try:
        results, degraded = await q_search.search_hybrid(
            session, repo, query, kinds, limit
        )
    except q_search.UnknownRepositoryError as exc:
        return {"error": f"unknown repository {exc}"}
    except ValueError as exc:  # e.g. invalid kind value
        return {"error": str(exc)}
    return {
        "degraded": degraded,
        "results": [
            {
                "qualified_name": r.node.qualified_name,
                "kind": r.node.kind,
                "file_path": r.node.file_path,
                "start_line": r.node.start_line,
                "end_line": r.node.end_line,
                "summary": r.node.summary,
                "score": r.score,
                "source": r.source,
            }
            for r in results
        ],
    }


async def get_node(
    session: AsyncSession, qualified_name: str, repo: str | None = None
) -> dict:
    node, error = await _resolve_node(session, qualified_name, repo)
    if error is not None:
        return error
    detail = await q_graph.node_detail(session, node.id)

    async def edges_for(direction_col, other_col):
        rows = await session.execute(
            select(Edge, Node.qualified_name)
            .join(Node, other_col == Node.id)
            .where(direction_col == node.id)
            .order_by(Edge.id)
            .limit(EDGE_CAP)
        )
        return [
            {
                "rel": edge.rel.value,
                "confidence": edge.confidence.value,
                "src_line": edge.src_line,
                "qualified_name": other_qname,
            }
            for edge, other_qname in rows.all()
        ]

    return {
        "node": detail["node"].model_dump(),
        "edge_counts": detail["edge_counts"],
        "edges_out": await edges_for(Edge.src_id, Edge.dst_id),
        "edges_in": await edges_for(Edge.dst_id, Edge.src_id),
    }


async def get_neighbors(
    session: AsyncSession,
    qualified_name: str,
    hops: int = 1,
    limit: int = 50,
    min_confidence: str | None = None,
) -> dict:
    node, error = await _resolve_node(session, qualified_name)
    if error is not None:
        return error
    if min_confidence is not None and min_confidence not in (
        "resolved",
        "llm_inferred",
        "name_match",
    ):
        return {"error": f"invalid min_confidence {min_confidence!r}"}
    result = await q_graph.ego(
        session, node.id, hops=hops, limit=limit, min_confidence=min_confidence
    )
    return {
        "nodes": [n.model_dump() for n in result["nodes"]],
        "edges": [e.model_dump() for e in result["edges"]],
    }


async def impact_of(
    session: AsyncSession,
    qualified_name: str,
    direction: str = "upstream",
    max_depth: int = 5,
) -> dict:
    if direction not in ("upstream", "downstream"):
        return {"error": f"invalid direction {direction!r}"}
    node, error = await _resolve_node(session, qualified_name)
    if error is not None:
        return error
    result = await q_graph.impact(
        session, node.id, direction=direction, max_depth=max_depth
    )
    return {
        "root": node.qualified_name,
        "direction": direction,
        "items": [item.model_dump() for item in result["items"]],
    }


def _message_dict(message: AgentMessage, agent_names: dict[int, str]) -> dict:
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "agent": agent_names.get(message.agent_id, f"#{message.agent_id}"),
        "subject": message.subject,
        "body": message.body,
        "node_id": message.node_id,
        "created_at": message.created_at.isoformat(),
    }


async def _agent_names(session: AsyncSession, agent_ids: set[int]) -> dict[int, str]:
    if not agent_ids:
        return {}
    rows = await session.execute(
        select(Agent.id, Agent.name).where(Agent.id.in_(sorted(agent_ids)))
    )
    return dict(rows.all())


async def post_message(
    session: AsyncSession,
    agent_name: str,
    body: str,
    subject: str | None = None,
    thread_id: int | None = None,
    node_qualified_name: str | None = None,
) -> dict:
    node_id = None
    if node_qualified_name is not None:
        node, error = await _resolve_node(session, node_qualified_name)
        if error is not None:
            return error
        node_id = node.id
    # self-registration: first post creates the agent; every post bumps last_seen
    agent = await get_or_create_agent(session, agent_name)
    try:
        message = await q_messages.create_message(
            session,
            agent_id=agent.id,
            body=body,
            subject=subject,
            thread_id=thread_id,
            node_id=node_id,
        )
    except q_messages.InvalidReferenceError as exc:
        return {"error": str(exc)}
    await session.commit()
    return {
        "id": message.id,
        "thread_id": message.thread_id,  # null = this message is a thread root
        "agent": agent.name,
        "node_id": node_id,
        "created_at": message.created_at.isoformat(),
    }


async def read_board(
    session: AsyncSession,
    limit: int = 20,
    thread_id: int | None = None,
    node_qualified_name: str | None = None,
    agent_name: str | None = None,
    since: str | None = None,
) -> dict:
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            return {"error": f"invalid ISO-8601 timestamp {since!r}"}

    if thread_id is not None:
        thread = await q_messages.list_thread(session, thread_id)
        if thread is None:
            return {"error": f"unknown thread {thread_id}"}
        names = await _agent_names(session, {m.agent_id for m in thread})
        return {"messages": [_message_dict(m, names) for m in thread]}

    node_id = None
    if node_qualified_name is not None:
        node, error = await _resolve_node(session, node_qualified_name)
        if error is not None:
            return error
        node_id = node.id
    agent_id = None
    if agent_name is not None:
        agent = await session.scalar(select(Agent).where(Agent.name == agent_name))
        if agent is None:
            return {"threads": []}
        agent_id = agent.id

    threads = await q_messages.list_threads(
        session, node_id=node_id, agent_id=agent_id, limit=limit, since=since_dt
    )
    names = await _agent_names(session, {root.agent_id for root, _, _ in threads})
    return {
        "threads": [
            {
                **_message_dict(root, names),
                "reply_count": reply_count,
                "last_activity": last_activity.isoformat()
                if last_activity is not None
                else None,
            }
            for root, reply_count, last_activity in threads
        ]
    }


async def kb_lookup(session: AsyncSession, term: str) -> dict:
    result = await q_kb.lookup(session, term)
    return {
        "match": result["match"],
        "results": [
            {
                "term": entry.term,
                "definition": entry.definition,
                "aliases": entry.aliases,
                "category": entry.category,
            }
            for entry in result["results"]
        ],
    }
