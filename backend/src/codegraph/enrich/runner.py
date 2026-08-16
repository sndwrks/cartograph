"""Phase orchestration shared by the CLI, ingest --enrich, and tests."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.models import Repository

from . import communities, docs, embeddings, kb, summaries
from .llm import LLMClient
from .voyage import EmbeddingClient

# docs runs FIRST so newly created doc/config nodes get summaries and
# embeddings in the same run — otherwise an immediate re-run would still
# have work to do, breaking the cache guarantee.
ALL_PHASES = ("docs", "summaries", "embeddings", "communities", "kb")

LLM_PHASES = frozenset({"docs", "summaries", "communities"})
EMBED_PHASES = frozenset({"embeddings", "kb"})


async def run_phases(
    session: AsyncSession,
    repo: Repository,
    phases: tuple[str, ...],
    llm: LLMClient | None = None,
    embedder: EmbeddingClient | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    results: dict[str, dict] = {}
    for phase in phases:
        if phase == "docs":
            assert llm is not None
            results[phase] = await docs.run(session, repo, llm, limit)
        elif phase == "summaries":
            assert llm is not None
            results[phase] = await summaries.run(session, repo, llm, limit)
        elif phase == "embeddings":
            assert embedder is not None
            results[phase] = await embeddings.run(session, repo, embedder, limit)
        elif phase == "communities":
            assert llm is not None
            results[phase] = await communities.run(
                session, repo, llm, force=force, limit=limit
            )
        elif phase == "kb":
            assert embedder is not None
            results[phase] = await kb.run(session, embedder, limit)
        else:
            raise ValueError(f"unknown phase {phase!r}")
    return results
