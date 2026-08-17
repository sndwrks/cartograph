"""Queries backing the tier-3 enrichment job (slice 13)."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.config import get_settings
from codegraph.models import (
    Community,
    CommunityEdge,
    Edge,
    EdgeConfidence,
    EdgeRel,
    KnowledgeEntry,
    Node,
    NodeKind,
)

SUMMARY_KINDS = (
    NodeKind.module,
    NodeKind.class_,
    NodeKind.function,
    NodeKind.method,
    NodeKind.doc,
    NodeKind.config,
)


async def nodes_needing_summary(
    session: AsyncSession,
    repository_id: int,
    min_lines: int,
    limit: int | None = None,
) -> list[Node]:
    stmt = (
        select(Node)
        .where(
            Node.repository_id == repository_id,
            Node.kind.in_(SUMMARY_KINDS),
            (Node.end_line - Node.start_line + 1) >= min_lines,
            # cache rule: skip when the summary was made from the current source
            or_(
                Node.summary.is_(None),
                Node.summary_source_hash.is_distinct_from(Node.content_hash),
            ),
        )
        .order_by(Node.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def set_summary(
    session: AsyncSession, node_id: int, summary: str, source_hash: str | None
) -> None:
    # a rewritten summary invalidates the embedding (the embeddings phase
    # then processes summary IS NOT NULL AND embedding IS NULL)
    await session.execute(
        update(Node)
        .where(Node.id == node_id)
        .values(summary=summary, summary_source_hash=source_hash, embedding=None)
    )


async def nodes_needing_embedding(
    session: AsyncSession, repository_id: int, limit: int | None = None
) -> list[Node]:
    stmt = (
        select(Node)
        .where(
            Node.repository_id == repository_id,
            Node.summary.is_not(None),
            Node.embedding.is_(None),
        )
        .order_by(Node.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def set_embeddings(
    session: AsyncSession, rows: list[tuple[int, list[float]]]
) -> None:
    if rows:
        await session.execute(
            update(Node),
            [{"id": node_id, "embedding": vector} for node_id, vector in rows],
        )


async def communities_needing_label(
    session: AsyncSession, repository_id: int, force: bool = False
) -> list[Community]:
    stmt = select(Community).where(
        Community.repository_id == repository_id,
        # naming a cluster of one costs an LLM call and tells you nothing
        Community.node_count >= get_settings().COMMUNITY_MIN_SIZE,
    )
    if not force:
        stmt = stmt.where(Community.label.is_(None))
    return list((await session.scalars(stmt.order_by(Community.id))).all())


async def community_top_members(
    session: AsyncSession, community_id: int, limit: int = 15
) -> list[Node]:
    return list(
        (
            await session.scalars(
                select(Node)
                .where(Node.community_id == community_id)
                .order_by(Node.pagerank.desc(), Node.id)
                .limit(limit)
            )
        ).all()
    )


async def community_neighbor_labels(
    session: AsyncSession, community_id: int
) -> list[str]:
    rows = await session.scalars(
        select(Community.label)
        .join(
            CommunityEdge,
            or_(
                CommunityEdge.src_community_id == Community.id,
                CommunityEdge.dst_community_id == Community.id,
            ),
        )
        .where(
            or_(
                CommunityEdge.src_community_id == community_id,
                CommunityEdge.dst_community_id == community_id,
            ),
            Community.id != community_id,
            Community.label.is_not(None),
        )
        .distinct()
    )
    return [label for label in rows.all() if label]


async def set_community_label(
    session: AsyncSession, community_id: int, label: str, summary: str
) -> None:
    await session.execute(
        update(Community)
        .where(Community.id == community_id)
        .values(label=label, summary=summary)
    )


async def get_artifact_node(
    session: AsyncSession, repository_id: int, path: str, kind: NodeKind
) -> Node | None:
    return await session.scalar(
        select(Node).where(
            Node.repository_id == repository_id,
            Node.qualified_name == path,
            Node.kind == kind,
        )
    )


async def upsert_artifact_node(
    session: AsyncSession,
    repository_id: int,
    path: str,
    kind: NodeKind,
    name: str,
    content_hash: str,
    line_count: int,
) -> Node:
    node = await get_artifact_node(session, repository_id, path, kind)
    if node is None:
        node = Node(
            repository_id=repository_id,
            kind=kind,
            name=name,
            qualified_name=path,
            file_path=path,
            start_line=1,
            end_line=line_count,
            content_hash=content_hash,
        )
        session.add(node)
        await session.flush()
    else:
        node.content_hash = content_hash
        node.end_line = line_count
        await session.flush()
    return node


async def replace_doc_references(
    session: AsyncSession, doc_node_id: int, target_ids: list[int]
) -> int:
    """Replace a doc's llm_inferred references edges with a fresh set."""
    await session.execute(
        delete(Edge).where(
            Edge.src_id == doc_node_id,
            Edge.rel == EdgeRel.references,
            Edge.confidence == EdgeConfidence.llm_inferred,
        )
    )
    for target_id in target_ids:
        session.add(
            Edge(
                src_id=doc_node_id,
                dst_id=target_id,
                rel=EdgeRel.references,
                confidence=EdgeConfidence.llm_inferred,
                src_line=None,
            )
        )
    await session.flush()
    return len(target_ids)


async def symbol_candidates(
    session: AsyncSession, repository_id: int
) -> list[tuple[int, str, str]]:
    """(id, name, qualified_name) of symbol nodes for doc linking."""
    rows = await session.execute(
        select(Node.id, Node.name, Node.qualified_name).where(
            Node.repository_id == repository_id,
            Node.kind.in_(
                (NodeKind.class_, NodeKind.function, NodeKind.method, NodeKind.module)
            ),
        )
    )
    return [tuple(row) for row in rows.all()]


async def kb_entries_needing_embedding(
    session: AsyncSession, limit: int | None = None
) -> list[KnowledgeEntry]:
    stmt = (
        select(KnowledgeEntry)
        .where(KnowledgeEntry.embedding.is_(None))
        .order_by(KnowledgeEntry.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def set_kb_embeddings(
    session: AsyncSession, rows: list[tuple[int, list[float]]]
) -> None:
    if rows:
        await session.execute(
            update(KnowledgeEntry),
            [{"id": entry_id, "embedding": vector} for entry_id, vector in rows],
        )
        # bulk update triggers onupdate for updated_at; acceptable


async def count_nodes_with_embedding(
    session: AsyncSession, repository_id: int
) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Node)
            .where(
                Node.repository_id == repository_id, Node.embedding.is_not(None)
            )
        )
    ) or 0
