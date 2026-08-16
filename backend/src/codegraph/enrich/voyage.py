"""Embedding client interface — tests inject fakes; production uses Voyage."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Protocol

from codegraph.config import get_settings
from codegraph.models import EMBED_DIM

EMBED_MODEL = "voyage-code-3"
EMBED_BATCH = 128

InputType = Literal["document", "query"]


class EmbeddingClient(Protocol):
    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]: ...


class VoyageEmbeddings:
    def __init__(self, api_key: str, model: str = EMBED_MODEL):
        import voyageai

        self._client = voyageai.AsyncClient(api_key=api_key)
        self._model = model

    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
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
