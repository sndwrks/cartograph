"""Phase: Voyage embeddings for summarized nodes (batched)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.config import get_settings
from codegraph.models import Repository
from codegraph.query import enrich as q

from .voyage import EmbeddingClient, batch_spans

logger = logging.getLogger(__name__)


async def run(
    session: AsyncSession,
    repo: Repository,
    embedder: EmbeddingClient,
    limit: int | None = None,
) -> dict:
    settings = get_settings()
    nodes = await q.nodes_needing_embedding(session, repo.id, limit)
    texts = [
        f"{node.qualified_name} ({node.kind.value}): {node.summary}" for node in nodes
    ]
    total = len(nodes)
    embedded = failed = 0

    logger.info("embeddings: %d nodes to embed", total)
    for start, end in batch_spans(
        texts, settings.EMBED_BATCH_SIZE, settings.EMBED_MAX_TOKENS_PER_REQUEST
    ):
        batch = nodes[start:end]
        try:
            vectors = await embedder.embed(texts[start:end], input_type="document")
        except Exception:
            logger.exception("embedding batch failed (%d texts)", end - start)
            failed += len(batch)
            continue
        await q.set_embeddings(
            session, [(node.id, vector) for node, vector in zip(batch, vectors)]
        )
        embedded += len(batch)
        # commit per batch so an interrupted run keeps everything up to here;
        # nodes_needing_embedding filters on embedding IS NULL, so the next run
        # picks up exactly where this one stopped
        await session.commit()
        logger.info(
            "embeddings: %d/%d done (embedded=%d failed=%d)",
            end,
            total,
            embedded,
            failed,
        )
    await session.commit()
    return {"embedded": embedded, "failed": failed}
