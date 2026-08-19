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

from cartograph.kb.types import UnknownKbTypeError, get_type, type_names
from cartograph.models import Agent, AgentMessage, Edge, Node, Repository
from cartograph.query import graph as q_graph
from cartograph.query import kb as q_kb
from cartograph.query import messages as q_messages
from cartograph.query import search as q_search
from cartograph.query.agents import get_or_create_agent
from cartograph.query.graph import (
    AmbiguousNodeNameError,
    NodeNameNotFoundError,
    resolve_node_by_name,
)
from cartograph.query.messages import UnknownRepositoryError

EDGE_CAP = 100  # per direction, in get_node
INDEX_CAP = 500  # entries returned by kb_get's type index


async def _resolve_node(
    session: AsyncSession, qualified_name: str, repo: str | None = None
) -> tuple[Node | None, dict | None]:
    """Thin adapter over query.graph.resolve_node_by_name (slice 19).

    Returns (node, None) on success, (None, error_dict) otherwise — including
    a candidates list when the name is ambiguous. The dict shapes below are a
    frozen contract: tests/mcp/test_board_tools.py and tests/mcp/test_tools.py
    assert on them byte-for-byte, so this catches the query layer's raised
    exceptions rather than changing what callers receive.
    """
    try:
        node = await resolve_node_by_name(session, qualified_name, repo)
    except UnknownRepositoryError as exc:
        return None, {"error": f"unknown repository {str(exc)!r}"}
    except NodeNameNotFoundError:
        return None, {"error": f"no node found for {qualified_name!r}"}
    except AmbiguousNodeNameError as exc:
        return None, {
            "error": f"ambiguous name {qualified_name!r} — pass a qualified name",
            "candidates": [
                {
                    "qualified_name": n.qualified_name,
                    "kind": n.kind.value,
                    "file_path": n.file_path,
                }
                for n in exc.candidates
            ],
        }
    return node, None


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
    repo: str | None = None,
) -> dict:
    node_id = None
    if node_qualified_name is not None:
        node, error = await _resolve_node(session, node_qualified_name, repo)
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
    repo: str | None = None,
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
        node, error = await _resolve_node(session, node_qualified_name, repo)
        if error is not None:
            return error
        node_id = node.id
    agent_id = None
    if agent_name is not None:
        agent = await session.scalar(select(Agent).where(Agent.name == agent_name))
        if agent is None:
            return {"threads": []}
        agent_id = agent.id

    try:
        threads = await q_messages.list_threads(
            session,
            node_id=node_id,
            agent_id=agent_id,
            repo_name=repo,
            limit=limit,
            since=since_dt,
        )
    except UnknownRepositoryError as exc:
        return {"error": f"unknown repository {str(exc)!r}"}
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


#: Same cap as the agent-board skill's message body, for the same reason: a
#: multi-result read materializes every body into context. A glossary entry
#: written to the 1-2 sentence rule never reaches it, so the common path is
#: lossless and the cap only bites a specification or runbook.
KB_BODY_CAP = 400

_SENTENCE_ENDINGS = (". ", "! ", "? ", ".\n", "!\n", "?\n")


def _truncate(body: str) -> tuple[str, bool]:
    """Cut at KB_BODY_CAP on a sentence boundary. Returns (text, was_cut)."""
    if len(body) <= KB_BODY_CAP:
        return body, False
    head = body[:KB_BODY_CAP]
    cut = max(head.rfind(ending) for ending in _SENTENCE_ENDINGS)
    if cut > 0:
        cut += 1  # keep the punctuation itself
    else:
        cut = head.rfind(" ")  # no sentence end: at least never mid-word
    if cut <= 0:
        cut = KB_BODY_CAP
    return head[:cut].rstrip() + " …", True


def _kb_result(entry, truncate: bool = True) -> dict:
    body, was_cut = _truncate(entry.body) if truncate else (entry.body, False)
    out = {
        "type": entry.type,
        "slug": entry.slug,
        "term": entry.title,
        "definition": body,
        "aliases": entry.aliases,
        "category": entry.category,
    }
    # only present when it happened — a conditional key costs nothing to read
    # and saves a token on the overwhelmingly common glossary hit
    if was_cut:
        out["truncated"] = True
    return out


async def _repo_filter(session: AsyncSession, repo: str | None):
    """Resolve a repo name to a lookup scope, or report an unknown one.

    Returns (repo_filter, error). Without this every read ran unscoped, and two
    repositories that each define the same term tie on every ordering key —
    so an agent got whichever row happened to have the lower id, reported as
    `match: "exact"`.
    """
    if repo is None:
        return "*", None
    repository = await session.scalar(
        select(Repository).where(Repository.name == repo)
    )
    if repository is None:
        return None, {"error": f"unknown repository {repo!r}"}
    return repository.id, None


async def kb_lookup(session: AsyncSession, term: str, repo: str | None = None) -> dict:
    repo_filter, error = await _repo_filter(session, repo)
    if error is not None:
        return error
    result = await q_kb.lookup(session, term, repo_filter=repo_filter)
    out = {
        "match": result["match"],
        "results": [_kb_result(entry) for entry in result["results"]],
    }
    # `{match, results}` is the FROZEN top level of this response. Anything
    # new goes inside a result object — tests/mcp/test_tools.py and
    # tests/api/test_kb.py both assert exact dict equality on the "none" case.
    if result["also_matched"]:
        out["also_matched"] = [_kb_result(e) for e in result["also_matched"]]
    return out


async def kb_get(
    session: AsyncSession,
    slug: str | None = None,
    type: str | None = None,
    repo: str | None = None,
) -> dict:
    """With a slug, one entry in full. With only a type, that type's index."""
    if type is not None:
        try:
            get_type(type)
        except UnknownKbTypeError:
            return {"error": f"unknown type {type!r}", "types": list(type_names())}
    repo_filter, error = await _repo_filter(session, repo)
    if error is not None:
        return error

    if slug is None:
        if type is None:
            return {
                "error": "pass a slug for one entry, or a type for that type's index",
                "types": list(type_names()),
            }
        rows, total = await q_kb.list_entry_index(
            session, type, repo_filter=repo_filter, limit=INDEX_CAP
        )
        out = {
            "type": type,
            "index": [{"slug": slug, "title": title} for slug, title in rows],
        }
        if total > len(rows):
            # The tool description tells the agent to read the index before
            # proposing. A silently clipped index sends it off to propose a
            # duplicate, so say so rather than look complete.
            out["truncated"] = True
            out["total"] = total
        return out

    entry = await q_kb.get_entry_by_slug(session, slug, type=type, repo_filter=repo_filter)
    if entry is None:
        return {"error": f"no published knowledge-base entry with slug {slug!r}"}
    # never truncated: kb_get is the escape hatch from kb_lookup's cap, so it
    # must have no way to fail you
    out = _kb_result(entry, truncate=False)
    out["payload"] = entry.payload or {}
    out["seq"] = entry.seq
    out["updated_at"] = entry.updated_at.isoformat()
    return out


async def kb_propose(
    session: AsyncSession,
    agent_name: str,
    type: str,
    slug: str,
    title: str,
    body: str,
    payload: dict | None = None,
    repo: str | None = None,
) -> dict:
    """Write a `proposed` entry. No lookup returns it until a human publishes.

    Errors carry what you need to retry, following _resolve_node's precedent.
    """
    try:
        kb_type = get_type(type)
    except UnknownKbTypeError:
        return {"error": f"unknown type {type!r}", "types": list(type_names())}

    repository_id = None
    if repo is not None:
        repository = await session.scalar(
            select(Repository).where(Repository.name == repo)
        )
        if repository is None:
            return {"error": f"unknown repository {repo!r}"}
        repository_id = repository.id

    # One query for all three answers we need about this slug.
    existing = await q_kb.find_by_slug(
        session,
        type=type,
        slug=slug,
        repository_id=repository_id,
        statuses=(q_kb.REJECTED, q_kb.PROPOSED, q_kb.PUBLISHED),
    )

    # A prior rejection is the one piece of human judgment that can reach a
    # later session. Report it and write nothing.
    rejected = existing.get(q_kb.REJECTED)
    if rejected is not None:
        return {
            "status": "rejected_before",
            "slug": rejected.slug,
            "reason": rejected.review_note,
            "rejected_at": rejected.updated_at.isoformat(),
        }

    # Idempotent: without this, one agent re-run buries the review queue —
    # and the queue is the whole feature.
    pending = existing.get(q_kb.PROPOSED)
    if pending is not None:
        return {"status": "duplicate", "id": pending.id, "slug": pending.slug}

    incumbent = existing.get(q_kb.PUBLISHED)

    # self-registration: the first proposal creates the agent, exactly like
    # the first board post
    agent = await get_or_create_agent(session, agent_name)
    try:
        entry = await q_kb.create_entry(
            session,
            title,
            body,
            type=type,
            slug=slug,
            payload=payload,
            repository_id=repository_id,
            status=q_kb.PROPOSED,
            source="mcp",
            created_by=f"agent:{agent.name}",
        )
    except q_kb.PayloadValidationError as exc:
        return {
            "error": f"payload invalid for type {type!r}",
            "fields": kb_type.payload_fields(),
            "detail": [
                {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
                for e in exc.errors
            ],
        }
    await session.commit()

    out = {
        "status": "proposed",
        "id": entry.id,
        "type": entry.type,
        "slug": entry.slug,
    }
    if incumbent is not None:
        out["revision_of"] = incumbent.slug
        out["published_title"] = incumbent.title
    return out
