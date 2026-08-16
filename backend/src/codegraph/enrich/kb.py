"""Phase: embed knowledge-base entries."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.query import enrich as q

from .voyage import EMBED_BATCH, EmbeddingClient

logger = logging.getLogger(__name__)


async def run(
    session: AsyncSession,
    embedder: EmbeddingClient,
    limit: int | None = None,
) -> dict:
    entries = await q.kb_entries_needing_embedding(session, limit)
    embedded = failed = 0
    for start in range(0, len(entries), EMBED_BATCH):
        batch = entries[start : start + EMBED_BATCH]
        texts = [f"{entry.term}: {entry.definition}" for entry in batch]
        try:
            vectors = await embedder.embed(texts, input_type="document")
        except Exception:
            logger.exception("kb embedding batch failed (%d texts)", len(texts))
            failed += len(batch)
            continue
        await q.set_kb_embeddings(
            session, [(entry.id, vector) for entry, vector in zip(batch, vectors)]
        )
        embedded += len(batch)
    await session.commit()
    return {"embedded": embedded, "failed": failed}
