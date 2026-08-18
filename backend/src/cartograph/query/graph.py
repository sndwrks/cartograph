"""Graph read queries shared by the API routers and MCP tools (slice 07)."""

from __future__ import annotations

from sqlalchemy import BigInteger, cast, func, literal, null, select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.schemas import (
    CommunityEdgeOut,
    CommunityOut,
    EdgeOut,
    ImpactItem,
    NodeOut,
    StubEdgeOut,
)
from cartograph.config import get_settings
from cartograph.models import (
    Community,
    CommunityEdge,
    Edge,
    EdgeConfidence,
    EdgeRel,
    Node,
    NodeKind,
)
from cartograph.query.ingest import get_repository_by_name

MAX_NODES = 2500  # the client never receives more than ~2500 renderable nodes
MAX_HOPS = 3
MAX_DEPTH = 10

# trust order: resolved > llm_inferred > name_match
_CONFIDENCE_ORDER = [
    EdgeConfidence.resolved,
    EdgeConfidence.llm_inferred,
    EdgeConfidence.name_match,
]


def _allowed_confidences(min_confidence: str | None) -> list[EdgeConfidence] | None:
    if min_confidence is None:
        return None
    floor = EdgeConfidence(min_confidence)
    return _CONFIDENCE_ORDER[: _CONFIDENCE_ORDER.index(floor) + 1]


async def overview(session: AsyncSession, repo_name: str) -> dict | None:
    repo = await get_repository_by_name(session, repo_name)
    if repo is None:
        return None
    min_size = get_settings().COMMUNITY_MIN_SIZE
    communities = (
        await session.scalars(
            select(Community)
            .where(
                Community.repository_id == repo.id,
                Community.node_count >= min_size,
            )
            .order_by(Community.id)
        )
    ).all()
    # an edge is only meaningful if both endpoints survived the size filter
    kept = {community.id for community in communities}
    community_edges = [
        edge
        for edge in (
            await session.scalars(
                select(CommunityEdge)
                .join(Community, CommunityEdge.src_community_id == Community.id)
                .where(Community.repository_id == repo.id)
                .order_by(
                    CommunityEdge.src_community_id, CommunityEdge.dst_community_id
                )
            )
        ).all()
        if edge.src_community_id in kept and edge.dst_community_id in kept
    ]
    return {
        "communities": [CommunityOut.from_community(c) for c in communities],
        "community_edges": [
            CommunityEdgeOut.from_community_edge(e) for e in community_edges
        ],
    }


async def community_graph(
    session: AsyncSession, community_id: int, limit: int = 500
) -> dict | None:
    community = await session.get(Community, community_id)
    if community is None:
        return None
    limit = min(limit, MAX_NODES)
    nodes = (
        await session.scalars(
            select(Node)
            .where(Node.community_id == community_id, Node.kind != NodeKind.file)
            .order_by(Node.pagerank.desc(), Node.id)
            .limit(limit)
        )
    ).all()
    ids = [n.id for n in nodes]
    edges: list[Edge] = []
    stubs: list[StubEdgeOut] = []
    if ids:
        edges = (
            await session.scalars(
                select(Edge)
                .where(
                    Edge.rel != EdgeRel.contains,
                    Edge.src_id.in_(ids),
                    Edge.dst_id.in_(ids),
                )
                .order_by(Edge.id)
            )
        ).all()
        stub_rows = await session.execute(
            select(Edge.src_id, Node.community_id, func.count())
            .join(Node, Edge.dst_id == Node.id)
            .where(
                Edge.rel != EdgeRel.contains,
                Edge.src_id.in_(ids),
                Node.community_id.is_not(None),
                Node.community_id != community_id,
            )
            .group_by(Edge.src_id, Node.community_id)
            .order_by(Edge.src_id, Node.community_id)
        )
        stubs = [
            StubEdgeOut(src_id=src_id, dst_community_id=dst_community, weight=weight)
            for src_id, dst_community, weight in stub_rows.all()
        ]
    return {
        "nodes": [NodeOut.from_node(n) for n in nodes],
        "edges": [EdgeOut.from_edge(e) for e in edges],
        "stub_edges": stubs,
    }


async def node_detail(session: AsyncSession, node_id: int) -> dict | None:
    node = await session.get(Node, node_id)
    if node is None:
        return None
    counts: dict[str, dict[str, dict[str, int]]] = {"in": {}, "out": {}}
    for direction, column in (("out", Edge.src_id), ("in", Edge.dst_id)):
        rows = await session.execute(
            select(Edge.rel, Edge.confidence, func.count())
            .where(column == node_id)
            .group_by(Edge.rel, Edge.confidence)
        )
        for rel, confidence, count in rows.all():
            counts[direction].setdefault(rel.value, {})[confidence.value] = count
    return {"node": NodeOut.from_node(node), "edge_counts": counts}


async def ego(
    session: AsyncSession,
    node_id: int,
    hops: int = 1,
    limit: int = 200,
    min_confidence: str | None = None,
) -> dict | None:
    root = await session.get(Node, node_id)
    if root is None:
        return None
    hops = min(hops, MAX_HOPS)
    limit = min(limit, MAX_NODES)
    allowed = _allowed_confidences(min_confidence)

    def confidence_filter(stmt):
        return stmt.where(Edge.confidence.in_(allowed)) if allowed else stmt

    visited: set[int] = {node_id}
    frontier: set[int] = {node_id}
    for _ in range(hops):
        if not frontier or len(visited) >= limit:
            break
        frontier_ids = sorted(frontier)
        stmt = confidence_filter(
            select(Edge.src_id, Edge.dst_id).where(
                Edge.rel != EdgeRel.contains,
                (Edge.src_id.in_(frontier_ids)) | (Edge.dst_id.in_(frontier_ids)),
            )
        )
        rows = (await session.execute(stmt)).all()
        neighbors = {n for pair in rows for n in pair} - visited
        frontier = set()
        for neighbor in sorted(neighbors):  # deterministic truncation
            if len(visited) >= limit:
                break
            visited.add(neighbor)
            frontier.add(neighbor)

    visited_ids = sorted(visited)
    nodes = (
        await session.scalars(
            select(Node).where(Node.id.in_(visited_ids)).order_by(Node.id)
        )
    ).all()
    edges = (
        await session.scalars(
            confidence_filter(
                select(Edge).where(
                    Edge.rel != EdgeRel.contains,
                    Edge.src_id.in_(visited_ids),
                    Edge.dst_id.in_(visited_ids),
                )
            ).order_by(Edge.id)
        )
    ).all()
    return {
        "nodes": [NodeOut.from_node(n) for n in nodes],
        "edges": [EdgeOut.from_edge(e) for e in edges],
    }


async def impact(
    session: AsyncSession,
    node_id: int,
    direction: str = "upstream",
    max_depth: int = 5,
    limit: int = 500,
) -> dict | None:
    root = await session.get(Node, node_id)
    if root is None:
        return None
    max_depth = min(max_depth, MAX_DEPTH)

    walk = (
        select(
            cast(literal(node_id), BigInteger).label("node_id"),
            literal(0).label("depth"),
            cast(null(), BigInteger).label("edge_id"),
        ).cte("walk", recursive=True)
    )
    if direction == "upstream":
        step = (
            select(Edge.src_id, walk.c.depth + 1, Edge.id)
            .join(walk, Edge.dst_id == walk.c.node_id)
            .where(walk.c.depth < max_depth, Edge.rel != EdgeRel.contains)
        )
    else:
        step = (
            select(Edge.dst_id, walk.c.depth + 1, Edge.id)
            .join(walk, Edge.src_id == walk.c.node_id)
            .where(walk.c.depth < max_depth, Edge.rel != EdgeRel.contains)
        )
    walk = walk.union(step)  # UNION (not ALL): dedup keeps cycles bounded

    ranked = (
        select(
            walk.c.node_id,
            walk.c.depth,
            walk.c.edge_id,
            func.row_number()
            .over(
                partition_by=walk.c.node_id,
                order_by=(walk.c.depth, walk.c.edge_id),
            )
            .label("rank"),
        ).subquery()
    )
    rows = (
        await session.execute(
            select(ranked.c.node_id, ranked.c.depth, ranked.c.edge_id)
            .where(ranked.c.rank == 1, ranked.c.node_id != node_id)
            .order_by(ranked.c.depth, ranked.c.node_id)
            .limit(limit)
        )
    ).all()

    node_ids = [node_id_ for node_id_, _, _ in rows]
    edge_ids = [edge_id for _, _, edge_id in rows if edge_id is not None]
    nodes = {
        n.id: n
        for n in (
            await session.scalars(select(Node).where(Node.id.in_(node_ids)))
        ).all()
    }
    edges = {
        e.id: e
        for e in (
            await session.scalars(select(Edge).where(Edge.id.in_(edge_ids)))
        ).all()
    }
    items = [
        ImpactItem(
            node=NodeOut.from_node(nodes[nid]),
            depth=depth,
            via=EdgeOut.from_edge(edges[edge_id]),
        )
        for nid, depth, edge_id in rows
        if nid in nodes and edge_id in edges
    ]
    return {"root_id": node_id, "items": items}


async def related_kb(
    session: AsyncSession, node_id: int, limit: int = 5
) -> list[dict] | None:
    """KB entries nearest to the node's embedding; [] until enrichment ran."""
    from cartograph.models import KnowledgeEntry  # local: avoids widening imports

    node = await session.get(Node, node_id)
    if node is None:
        return None
    if node.embedding is None:
        return []
    distance = KnowledgeEntry.embedding.cosine_distance(node.embedding)
    rows = (
        await session.execute(
            select(KnowledgeEntry, (1 - distance).label("score"))
            .where(KnowledgeEntry.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    return [
        {
            "term": entry.term,
            "definition": entry.definition,
            "category": entry.category,
            "score": score,
        }
        for entry, score in rows
    ]


async def god_nodes(
    session: AsyncSession,
    repo_name: str,
    limit: int = 20,
    kind: str | None = None,
    community_id: int | None = None,
) -> list[NodeOut] | None:
    repo = await get_repository_by_name(session, repo_name)
    if repo is None:
        return None
    stmt = (
        select(Node)
        .where(Node.repository_id == repo.id, Node.kind != NodeKind.file)
        .order_by(
            Node.pagerank.desc(),
            (Node.degree_in + Node.degree_out).desc(),
            Node.id,
        )
        .limit(min(limit, MAX_NODES))
    )
    if kind is not None:
        stmt = stmt.where(Node.kind == NodeKind(kind))
    if community_id is not None:
        stmt = stmt.where(Node.community_id == community_id)
    nodes = (await session.scalars(stmt)).all()
    return [NodeOut.from_node(n) for n in nodes]
