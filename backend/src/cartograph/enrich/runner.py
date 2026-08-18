"""Phase orchestration shared by the CLI, ingest --enrich, and tests."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Repository

from . import communities, docs, embeddings, kb, summaries
from .llm import LLMClient
from .voyage import EmbeddingClient

# docs runs FIRST so newly created doc/config nodes get summaries and
# embeddings in the same run — otherwise an immediate re-run would still
# have work to do, breaking the cache guarantee.
ALL_PHASES = ("docs", "summaries", "embeddings", "communities", "kb")

LLM_PHASES = frozenset({"docs", "summaries", "communities"})
EMBED_PHASES = frozenset({"embeddings", "kb"})

# every phase counts its own write-offs rather than raising, so "the process
# exited 0" is not evidence the run did any work. Callers use this to tell a
# clean run from one that merely finished.
EXIT_PARTIAL_FAILURE = 3


def failed_phases(results: dict) -> list[tuple[str, int]]:
    """Phases that finished but wrote off work, as (phase, failed) pairs."""
    return [
        (phase, stats["failed"])
        for phase, stats in results.items()
        if isinstance(stats, dict) and stats.get("failed")
    ]


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
