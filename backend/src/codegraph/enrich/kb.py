"""Phase: embed knowledge-base entries."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.config import get_settings
from codegraph.query import enrich as q

from .voyage import EmbeddingClient, batch_spans

logger = logging.getLogger(__name__)


async def run(
    session: AsyncSession,
    embedder: EmbeddingClient,
    limit: int | None = None,
) -> dict:
    settings = get_settings()
    entries = await q.kb_entries_needing_embedding(session, limit)
    texts = [f"{entry.term}: {entry.definition}" for entry in entries]
    embedded = failed = 0

    for start, end in batch_spans(
        texts, settings.EMBED_BATCH_SIZE, settings.EMBED_MAX_TOKENS_PER_REQUEST
    ):
        batch = entries[start:end]
        try:
            vectors = await embedder.embed(texts[start:end], input_type="document")
        except Exception:
            logger.exception("kb embedding batch failed (%d texts)", end - start)
            failed += len(batch)
            continue
        await q.set_kb_embeddings(
            session, [(entry.id, vector) for entry, vector in zip(batch, vectors)]
        )
        embedded += len(batch)
        # commit per batch so an interrupted run keeps everything up to here
        await session.commit()
    await session.commit()
    return {"embedded": embedded, "failed": failed}
