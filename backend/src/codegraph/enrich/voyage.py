"""Embedding client interface — tests inject fakes; production uses Voyage."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Literal, Protocol

from codegraph.config import get_settings
from codegraph.models import EMBED_DIM

EMBED_MODEL = "voyage-code-3"

InputType = Literal["document", "query"]


def estimate_tokens(text: str) -> int:
    """Cheap upper-ish estimate. Voyage's real tokenizer needs the `tokenizers`
    package and pulls a model off the HF hub at runtime — far too much machinery
    for a batch-size guard that only has to be roughly right."""
    return len(text) // 4 + 1


def batch_spans(
    texts: list[str], max_items: int, max_tokens: int
) -> Iterator[tuple[int, int]]:
    """Yield (start, end) slices bounded by item count and estimated tokens.

    A single text over the token budget still gets its own span rather than
    being dropped — Voyage truncates oversized inputs server-side.
    """
    max_items = max(1, max_items)
    start = 0
    tokens = 0
    for index, text in enumerate(texts):
        cost = estimate_tokens(text)
        full = index - start >= max_items
        over = max_tokens > 0 and index > start and tokens + cost > max_tokens
        if full or over:
            yield start, index
            start = index
            tokens = 0
        tokens += cost
    if start < len(texts):
        yield start, len(texts)


class EmbeddingClient(Protocol):
    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]: ...


class VoyageEmbeddings:
    def __init__(self, api_key: str, model: str = EMBED_MODEL):
        import voyageai

        settings = get_settings()
        # voyageai ships tenacity backoff for 429/503/timeout but defaults
        # max_retries to 0, which disables it entirely.
        self._client = voyageai.AsyncClient(
            api_key=api_key,
            max_retries=max(1, settings.EMBED_MAX_RETRIES),
            timeout=settings.EMBED_TIMEOUT_S,
        )
        self._model = model
        self._min_interval = settings.EMBED_MIN_INTERVAL_S
        self._gate = asyncio.Lock()
        self._last_call = 0.0

    async def _throttle(self) -> None:
        """Space requests out by EMBED_MIN_INTERVAL_S, for accounts whose rate
        limit is low enough that retrying into it just burns the retry budget."""
        if self._min_interval <= 0:
            return
        async with self._gate:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        await self._throttle()
        result = await self._client.embed(
            texts,
            model=self._model,
            input_type=input_type,
            output_dimension=EMBED_DIM,
        )
        embeddings = result.embeddings
        if embeddings and len(embeddings[0]) != EMBED_DIM:
            raise RuntimeError(
                f"embedding dimension {len(embeddings[0])} != EMBED_DIM {EMBED_DIM}"
            )
        return embeddings


def build_embedder() -> VoyageEmbeddings:
    api_key = get_settings().VOYAGE_API_KEY
    if not api_key:
        raise SystemExit(
            "VOYAGE_API_KEY is not set — required for the embeddings and kb "
            "phases. Set it in .env."
        )
    return VoyageEmbeddings(api_key)


@lru_cache
def get_default_embedder() -> VoyageEmbeddings | None:
    """Lazy embedder for the request path (search, KB fallback); None if keyless."""
    api_key = get_settings().VOYAGE_API_KEY
    return VoyageEmbeddings(api_key) if api_key else None
