"""Queries backing the metrics/clustering job (slice 06)."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Community, CommunityEdge, Edge, EdgeRel, Node, NodeKind

SYMBOL_KINDS = (
    NodeKind.module,
    NodeKind.class_,
    NodeKind.function,
    NodeKind.method,
    NodeKind.doc,
    NodeKind.config,
)


async def load_graph(
    session: AsyncSession, repository_id: int
) -> tuple[list[int], list[tuple[int, int]]]:
    """Symbol node ids and the non-contains edges among them, both id-ordered."""
    ids = list(
        (
            await session.scalars(
                select(Node.id)
                .where(
                    Node.repository_id == repository_id,
                    Node.kind.in_(SYMBOL_KINDS),
                )
                .order_by(Node.id)
            )
        ).all()
    )
    if not ids:
        return [], []
    rows = await session.execute(
        select(Edge.src_id, Edge.dst_id)
        .where(
            Edge.rel != EdgeRel.contains,
            Edge.src_id.in_(ids),
            Edge.dst_id.in_(ids),
        )
        .order_by(Edge.id)
    )
    return ids, [(src, dst) for src, dst in rows.all()]


async def write_node_metrics(session: AsyncSession, rows: list[dict]) -> None:
    """Bulk update degree_in/degree_out/pagerank; rows carry the node pk as 'id'."""
    if rows:
        await session.execute(update(Node), rows)


async def snapshot_labeled_communities(
    session: AsyncSession, repository_id: int
) -> list[tuple[set[int], str | None, str | None]]:
    """(member node ids, label, summary) for communities carrying tier-3 text."""
    labeled = (
        await session.execute(
            select(Community.id, Community.label, Community.summary).where(
                Community.repository_id == repository_id,
                (Community.label.is_not(None)) | (Community.summary.is_not(None)),
            )
        )
    ).all()
    result = []
    for community_id, label, summary in labeled:
        members = set(
            (
                await session.scalars(
                    select(Node.id).where(Node.community_id == community_id)
                )
            ).all()
        )
        result.append((members, label, summary))
    return result


async def delete_communities(session: AsyncSession, repository_id: int) -> None:
    # community_edges rows cascade; Node.community_id is ON DELETE SET NULL
    await session.execute(
        delete(Community).where(Community.repository_id == repository_id)
    )


async def insert_communities(session: AsyncSession, rows: list[dict]) -> list[int]:
    """Insert Community rows, returning their ids in input order."""
    communities = [Community(**row) for row in rows]
    session.add_all(communities)
    await session.flush()
    return [community.id for community in communities]


async def assign_node_communities(
    session: AsyncSession, assignments: list[dict]
) -> None:
    """Bulk update Node.community_id; rows carry the node pk as 'id'."""
    if assignments:
        await session.execute(update(Node), assignments)


async def insert_community_edges(session: AsyncSession, rows: list[dict]) -> None:
    if rows:
        session.add_all([CommunityEdge(**row) for row in rows])
        await session.flush()
