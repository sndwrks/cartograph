"""Search queries: trigram text now, semantic/hybrid signatures for slice 13."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.api.schemas import NodeOut, SearchResult
from codegraph.enrich.voyage import EmbeddingClient, get_default_embedder
from codegraph.models import Node, NodeKind
from codegraph.query.ingest import get_repository_by_name

RRF_K = 60
# pg_trgm's default 0.3 threshold misses short fuzzy fragments ("ordr" vs
# "OrderService" is 0.2); lower it for the session running the search
TRGM_THRESHOLD = 0.1


class UnknownRepositoryError(LookupError):
    pass


async def _repo_filter(session: AsyncSession, stmt, repo_name: str | None):
    if repo_name is None:
        return stmt
    repo = await get_repository_by_name(session, repo_name)
    if repo is None:
        raise UnknownRepositoryError(repo_name)
    return stmt.where(Node.repository_id == repo.id)


async def search_text(
    session: AsyncSession,
    repo_name: str | None,
    q: str,
    kinds: Sequence[str] | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    await session.execute(text("SELECT set_limit(:t)"), {"t": TRGM_THRESHOLD})
    score = func.greatest(
        func.similarity(Node.name, q), func.similarity(Node.qualified_name, q)
    ).label("score")
    stmt = (
        select(Node, score)
        .where(
            Node.kind != NodeKind.file,
            (Node.name.op("%")(q)) | (Node.qualified_name.op("%")(q)),
        )
        .order_by(score.desc(), Node.id)
        .limit(limit)
    )
    if kinds:
        stmt = stmt.where(Node.kind.in_([NodeKind(k) for k in kinds]))
    stmt = await _repo_filter(session, stmt, repo_name)
    rows = (await session.execute(stmt)).all()
    return [
        SearchResult(node=NodeOut.from_node(node), score=score, source="text")
        for node, score in rows
    ]


async def search_semantic(
    session: AsyncSession,
    repo_name: str | None,
    q: str,
    kinds: Sequence[str] | None = None,
    limit: int = 20,
    embedder: EmbeddingClient | None = None,
) -> list[SearchResult]:
    """Cosine search over node embeddings (HNSW index); score = 1 - distance."""
    embedder = embedder or get_default_embedder()
    if embedder is None:
        raise NotImplementedError("semantic search requires VOYAGE_API_KEY")
    [query_vector] = await embedder.embed([q], input_type="query")
    distance = Node.embedding.cosine_distance(query_vector)
    stmt = (
        select(Node, (1 - distance).label("score"))
        .where(Node.kind != NodeKind.file, Node.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    if kinds:
        stmt = stmt.where(Node.kind.in_([NodeKind(k) for k in kinds]))
    stmt = await _repo_filter(session, stmt, repo_name)
    rows = (await session.execute(stmt)).all()
    return [
        SearchResult(node=NodeOut.from_node(node), score=score, source="semantic")
        for node, score in rows
    ]


async def search_hybrid(
    session: AsyncSession,
    repo_name: str | None,
    q: str,
    kinds: Sequence[str] | None = None,
    limit: int = 20,
    embedder: EmbeddingClient | None = None,
) -> tuple[list[SearchResult], bool]:
    """Text + semantic merged via RRF. Returns (results, degraded).

    Degrades to text-only (degraded=True) when no embedding client is
    available, so keyless deployments keep working.
    """
    text_results = await search_text(session, repo_name, q, kinds, limit)
    try:
        semantic_results = await search_semantic(
            session, repo_name, q, kinds, limit, embedder=embedder
        )
    except NotImplementedError:
        return text_results, True

    by_id = {r.node.id: r for r in [*semantic_results, *text_results]}
    merged = rrf_merge(
        [
            [r.node.id for r in text_results],
            [r.node.id for r in semantic_results],
        ]
    )
    return [
        SearchResult(node=by_id[node_id].node, score=score, source="hybrid")
        for node_id, score in merged[:limit]
    ], False


def rrf_merge(
    rankings: Sequence[Sequence[int]], k: int = RRF_K
) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: score(id) = sum over lists of 1/(k + rank)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
