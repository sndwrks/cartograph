"""Phase: embed knowledge-base entries."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.config import get_settings
from cartograph.kb.types import REGISTRY
from cartograph.kb.views import KbEntryView
from cartograph.query import enrich as q

from .voyage import EmbeddingClient, batch_spans

logger = logging.getLogger(__name__)


async def run(
    session: AsyncSession,
    embedder: EmbeddingClient,
    limit: int | None = None,
) -> dict:
    settings = get_settings()
    candidates = await q.kb_entries_needing_embedding(session, limit)
    embedded = failed = 0

    # Each type decides what it embeds, so a decision embeds its context and
    # consequences rather than the glossary's "title: body". An entry whose
    # type or payload is unusable is written off, not raised — same contract as
    # every other phase, so failed_phases() -> EXIT_PARTIAL_FAILURE still holds.
    pairs: list[tuple] = []
    for entry in candidates:
        try:
            kb_type = REGISTRY[entry.type]
            pairs.append((entry, kb_type.embed_text(KbEntryView.from_model(entry))))
        except Exception:
            logger.exception(
                "kb embed_text failed for entry %s (type %r)", entry.id, entry.type
            )
            failed += 1
    entries = [entry for entry, _ in pairs]
    texts = [text for _, text in pairs]

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
