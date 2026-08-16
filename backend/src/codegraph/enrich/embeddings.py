"""Phase: Voyage embeddings for summarized nodes (batched)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.models import Repository
from codegraph.query import enrich as q

from .voyage import EMBED_BATCH, EmbeddingClient

logger = logging.getLogger(__name__)


async def run(
    session: AsyncSession,
    repo: Repository,
    embedder: EmbeddingClient,
    limit: int | None = None,
) -> dict:
    nodes = await q.nodes_needing_embedding(session, repo.id, limit)
    embedded = failed = 0
    for start in range(0, len(nodes), EMBED_BATCH):
        batch = nodes[start : start + EMBED_BATCH]
        texts = [
            f"{node.qualified_name} ({node.kind.value}): {node.summary}"
            for node in batch
        ]
        try:
            vectors = await embedder.embed(texts, input_type="document")
        except Exception:
            logger.exception("embedding batch failed (%d texts)", len(texts))
            failed += len(batch)
            continue
        await q.set_embeddings(
            session, [(node.id, vector) for node, vector in zip(batch, vectors)]
        )
        embedded += len(batch)
    await session.commit()
    return {"embedded": embedded, "failed": failed}
