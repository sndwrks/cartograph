"""Knowledge-base queries with the deterministic lookup contract (slice 08)."""

from __future__ import annotations

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.enrich.voyage import EmbeddingClient, get_default_embedder
from codegraph.models import KnowledgeEntry


class DuplicateTermError(ValueError):
    pass


async def _term_taken(
    session: AsyncSession, term: str, exclude_id: int | None = None
) -> bool:
    stmt = select(KnowledgeEntry.id).where(
        func.lower(KnowledgeEntry.term) == term.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(KnowledgeEntry.id != exclude_id)
    return (await session.scalar(stmt)) is not None


async def create_entry(
    session: AsyncSession,
    term: str,
    definition: str,
    aliases: list[str] | None = None,
    category: str | None = None,
) -> KnowledgeEntry:
    if await _term_taken(session, term):
        raise DuplicateTermError(term)
    entry = KnowledgeEntry(
        term=term, definition=definition, aliases=aliases, category=category
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(
    session: AsyncSession,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[KnowledgeEntry]:
    stmt = select(KnowledgeEntry).order_by(KnowledgeEntry.term).limit(limit).offset(offset)
    if category is not None:
        stmt = stmt.where(KnowledgeEntry.category == category)
    return list((await session.scalars(stmt)).all())


async def get_entry(session: AsyncSession, entry_id: int) -> KnowledgeEntry | None:
    return await session.get(KnowledgeEntry, entry_id)


async def update_entry(
    session: AsyncSession, entry_id: int, fields: dict
) -> KnowledgeEntry | None:
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        return None
    new_term = fields.get("term")
    if new_term is not None and await _term_taken(session, new_term, exclude_id=entry_id):
        raise DuplicateTermError(new_term)
    for key, value in fields.items():
        setattr(entry, key, value)
    if "term" in fields or "definition" in fields:
        entry.embedding = None  # the kb enrich phase re-embeds edits
    await session.flush()
    return entry


async def delete_entry(session: AsyncSession, entry_id: int) -> bool:
    result = await session.execute(
        delete(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    )
    return bool(result.rowcount)


async def lookup(
    session: AsyncSession, term: str, embedder: EmbeddingClient | None = None
) -> dict:
    """Deterministic lookup: exact ci-term match, then alias match, then the
    vector fallback (slice 13). Steps 1-2 are the determinism guarantee and
    never change.
    """
    exact = await session.scalar(
        select(KnowledgeEntry).where(func.lower(KnowledgeEntry.term) == term.lower())
    )
    if exact is not None:
        return {"match": "exact", "results": [exact]}

    alias_hits = (
        await session.scalars(
            select(KnowledgeEntry)
            .where(
                text(
                    "EXISTS (SELECT 1 FROM unnest(aliases) AS al "
                    "WHERE lower(al) = lower(:term))"
                ).bindparams(term=term)
            )
            .order_by(KnowledgeEntry.term)
        )
    ).all()
    if alias_hits:
        return {"match": "alias", "results": list(alias_hits)}

    embedder = embedder or get_default_embedder()
    if embedder is not None:
        try:
            [query_vector] = await embedder.embed([term], input_type="query")
        except Exception:
            return {"match": "none", "results": []}
        vector_hits = (
            await session.scalars(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.embedding.is_not(None))
                .order_by(KnowledgeEntry.embedding.cosine_distance(query_vector))
                .limit(5)
            )
        ).all()
        if vector_hits:
            return {"match": "vector", "results": list(vector_hits)}

    return {"match": "none", "results": []}
