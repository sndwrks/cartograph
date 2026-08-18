"""Knowledge-base queries with the deterministic lookup contract.

Slice 08 established the contract; slice 15 made entries typed without moving
it. Tiers 1 and 2 stay pure indexed SQL and only ever gain *conjunctive*
filters — a narrowing, never a change of meaning.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import case, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from cartograph.enrich.voyage import EmbeddingClient, get_default_embedder
from cartograph.kb.types import (
    DEFAULT_TYPE,
    LOOKUP_PRECEDENCE,
    UnknownKbTypeError,
    get_type,
    types_with_lookup_key,
)
from cartograph.models import KnowledgeEntry

logger = logging.getLogger(__name__)

PROPOSED = "proposed"
PUBLISHED = "published"
REJECTED = "rejected"
ARCHIVED = "archived"
STATUSES = (PROPOSED, PUBLISHED, REJECTED, ARCHIVED)

#: Which prior statuses each target status may be reached from. Publishing an
#: archived entry is allowed so a superseded decision can be brought back.
TRANSITIONS: dict[str, frozenset[str]] = {
    PUBLISHED: frozenset({PROPOSED, ARCHIVED}),
    REJECTED: frozenset({PROPOSED}),
    ARCHIVED: frozenset({PUBLISHED}),
}

#: Changing any of these changes what `KbType.embed_text` would produce, so the
#: embedding has to be re-earned. Coarse on purpose — introspecting embed_text
#: to narrow it would be clever and wrong the first time a type changes.
EMBEDDING_FIELDS = frozenset({"title", "body", "payload", "type"})

#: int -> that repo plus globals; None -> globals only; "*" -> no filter.
RepoFilter = int | None | Literal["*"]

VECTOR_LIMIT = 5


class DuplicateTermError(ValueError):
    """A published entry already owns this title or slug in the same scope."""

    def __init__(self, value: str, existing_id: int | None = None) -> None:
        super().__init__(value)
        self.value = value
        self.existing_id = existing_id


class PayloadValidationError(ValueError):
    def __init__(self, type_name: str, errors: list) -> None:
        super().__init__(f"payload invalid for type {type_name!r}")
        self.type_name = type_name
        self.errors = errors


class InvalidTransitionError(ValueError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"cannot move a {current} entry to {target}")
        self.current = current
        self.target = target


__all__ = [
    "ARCHIVED",
    "PROPOSED",
    "PUBLISHED",
    "REJECTED",
    "STATUSES",
    "DuplicateTermError",
    "InvalidTransitionError",
    "PayloadValidationError",
    "UnknownKbTypeError",
    "count_entries",
    "create_entry",
    "delete_entry",
    "entries_for_export",
    "find_by_slug",
    "get_entry",
    "get_entry_by_slug",
    "list_entries",
    "list_entry_index",
    "lookup",
    "next_seq",
    "set_status",
    "update_entry",
]


# ---- helpers -------------------------------------------------------------


def _validate_payload(type_name: str, payload: dict | None) -> dict:
    try:
        return get_type(type_name).validate_payload(payload)
    except ValidationError as exc:
        raise PayloadValidationError(type_name, exc.errors()) from exc


def _scope_key(repository_id: int | None):
    """Mirrors coalesce(repository_id, 0) in the unique indexes."""
    return func.coalesce(KnowledgeEntry.repository_id, 0) == (repository_id or 0)


def _scoped(stmt, repo_filter: RepoFilter):
    if repo_filter == "*":
        return stmt
    if repo_filter is None:
        return stmt.where(KnowledgeEntry.repository_id.is_(None))
    return stmt.where(
        or_(
            KnowledgeEntry.repository_id == repo_filter,
            KnowledgeEntry.repository_id.is_(None),
        )
    )


def _precedence():
    """Type precedence as a SQL CASE, so ordering happens in one round trip."""
    return case(
        {name: rank for rank, name in enumerate(LOOKUP_PRECEDENCE)},
        value=KnowledgeEntry.type,
        else_=len(LOOKUP_PRECEDENCE),
    )


def _ranked(stmt):
    # repository_id IS NULL sorts False (0) first, so a repo-scoped row
    # outranks a global one. This is total only WITHIN one scope: with
    # repo_filter="*" two entries from different repositories tie on both keys
    # and fall through to id, which is arbitrary. Callers that need a
    # determinate answer must pass a repo_filter — every agent-facing tool does.
    return stmt.order_by(
        _precedence(), KnowledgeEntry.repository_id.is_(None), KnowledgeEntry.id
    )


async def _collision(
    session: AsyncSession,
    *,
    type: str,
    repository_id: int | None,
    title: str,
    slug: str,
    exclude_id: int | None = None,
) -> int | None:
    """Id of the published row this title/slug would collide with, if any."""
    stmt = select(KnowledgeEntry.id).where(
        KnowledgeEntry.type == type,
        KnowledgeEntry.status == PUBLISHED,
        _scope_key(repository_id),
        or_(
            func.lower(KnowledgeEntry.title) == title.lower(),
            func.lower(KnowledgeEntry.slug) == slug.lower(),
        ),
    )
    if exclude_id is not None:
        stmt = stmt.where(KnowledgeEntry.id != exclude_id)
    return await session.scalar(stmt.order_by(KnowledgeEntry.id).limit(1))


async def _flush(session: AsyncSession, title: str) -> None:
    """Flush, translating a lost uniqueness race into `DuplicateTermError`.

    `_collision()` is a read-then-write with no lock, so two concurrent
    publishes of the same title can both pass it and the loser trips the
    partial unique index at flush time. Without this it surfaces as an
    unhandled IntegrityError — an HTTP 500 for a condition that is a clean 409
    on the identical non-racing path.
    """
    try:
        await session.flush()
    except IntegrityError as exc:
        # the failed statement poisons the transaction; nothing after this
        # point could commit anyway
        await session.rollback()
        raise DuplicateTermError(title) from exc


async def next_seq(
    session: AsyncSession, type: str, repository_id: int | None
) -> int:
    """Highest existing number plus one, race-safe without a retry loop.

    The advisory lock is transaction-scoped and this is a low-frequency write
    path; ix_kb_seq is the backstop if two writers ever slip past it.
    """
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtext(f"kb_seq:{type}:{repository_id or 0}")
            )
        )
    )
    current = await session.scalar(
        select(func.max(KnowledgeEntry.seq)).where(
            KnowledgeEntry.type == type, _scope_key(repository_id)
        )
    )
    return (current or 0) + 1


# ---- CRUD ----------------------------------------------------------------


async def create_entry(
    session: AsyncSession,
    title: str,
    body: str,
    aliases: list[str] | None = None,
    category: str | None = None,
    *,
    type: str = DEFAULT_TYPE,
    slug: str | None = None,
    payload: dict | None = None,
    repository_id: int | None = None,
    status: str = PUBLISHED,
    source: str | None = None,
    created_by: str | None = None,
) -> KnowledgeEntry:
    """Create an entry.

    The first five parameters keep the pre-typed positional order
    `(session, term, definition, aliases, category)` — callers in the existing
    test suite pass them positionally, and that compatibility is deliberate.
    """
    kb_type = get_type(type)
    validated = _validate_payload(type, payload)
    slug = slug or kb_type.default_slug(title, validated)

    if status == PUBLISHED:
        clash = await _collision(
            session, type=type, repository_id=repository_id, title=title, slug=slug
        )
        if clash is not None:
            raise DuplicateTermError(title, existing_id=clash)

    entry = KnowledgeEntry(
        type=type,
        slug=slug,
        title=title,
        body=body,
        aliases=aliases,
        payload=validated,
        status=status,
        category=category,
        repository_id=repository_id,
        source=source,
        created_by=created_by,
    )
    if status == PUBLISHED and kb_type.assigns_seq:
        entry.seq = await next_seq(session, type, repository_id)
    session.add(entry)
    await _flush(session, title)
    return entry


def _filtered(
    stmt,
    *,
    type: str | None,
    status: str | None,
    repo_filter: RepoFilter,
    category: str | None,
    q: str | None,
):
    if type is not None:
        stmt = stmt.where(KnowledgeEntry.type == type)
    if status is not None:
        stmt = stmt.where(KnowledgeEntry.status == status)
    if category is not None:
        stmt = stmt.where(KnowledgeEntry.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(KnowledgeEntry.title.ilike(like), KnowledgeEntry.body.ilike(like))
        )
    return _scoped(stmt, repo_filter)


async def list_entries(
    session: AsyncSession,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    *,
    type: str | None = None,
    status: str | None = PUBLISHED,
    repo_filter: RepoFilter = "*",
    q: str | None = None,
) -> list[KnowledgeEntry]:
    stmt = _filtered(
        select(KnowledgeEntry),
        type=type,
        status=status,
        repo_filter=repo_filter,
        category=category,
        q=q,
    )
    stmt = stmt.order_by(_precedence(), KnowledgeEntry.title, KnowledgeEntry.id)
    # Nothing on a list path reads the 1024-dim vector; loading it turns a
    # 200-row page into ~200k floats materialized for nothing.
    stmt = stmt.options(defer(KnowledgeEntry.embedding))
    return list((await session.scalars(stmt.limit(limit).offset(offset))).all())


async def count_entries(
    session: AsyncSession,
    category: str | None = None,
    *,
    type: str | None = None,
    status: str | None = PUBLISHED,
    repo_filter: RepoFilter = "*",
    q: str | None = None,
) -> int:
    stmt = _filtered(
        select(func.count()).select_from(KnowledgeEntry),
        type=type,
        status=status,
        repo_filter=repo_filter,
        category=category,
        q=q,
    )
    return (await session.scalar(stmt)) or 0


async def list_entry_index(
    session: AsyncSession,
    type: str,
    *,
    repo_filter: RepoFilter = "*",
    limit: int = 500,
) -> tuple[list[tuple[str, str]], int]:
    """(slug, title) pairs for one type, plus the unclipped total.

    Columns only: the caller renders an index and never reads a body, so
    selecting whole rows would drag the 1024-dim embedding along with them.
    Returning `total` lets the caller say when the list was clipped instead of
    presenting a partial index as complete.
    """
    base = _scoped(
        select(KnowledgeEntry.slug, KnowledgeEntry.title).where(
            KnowledgeEntry.type == type, KnowledgeEntry.status == PUBLISHED
        ),
        repo_filter,
    )
    rows = (
        await session.execute(
            base.order_by(KnowledgeEntry.title, KnowledgeEntry.id).limit(limit)
        )
    ).all()
    total = await count_entries(session, type=type, repo_filter=repo_filter)
    return [(slug, title) for slug, title in rows], total


async def get_entry(session: AsyncSession, entry_id: int) -> KnowledgeEntry | None:
    return await session.get(KnowledgeEntry, entry_id)


async def get_entry_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    type: str | None = None,
    status: str | None = PUBLISHED,
    repo_filter: RepoFilter = "*",
) -> KnowledgeEntry | None:
    stmt = select(KnowledgeEntry).where(func.lower(KnowledgeEntry.slug) == slug.lower())
    if type is not None:
        stmt = stmt.where(KnowledgeEntry.type == type)
    if status is not None:
        stmt = stmt.where(KnowledgeEntry.status == status)
    return await session.scalar(_ranked(_scoped(stmt, repo_filter)).limit(1))


async def find_by_slug(
    session: AsyncSession,
    *,
    type: str,
    slug: str,
    repository_id: int | None,
    statuses: tuple[str, ...],
) -> dict[str, KnowledgeEntry]:
    """Most recent entry per status for this slug, as {status: entry}.

    Unlike `get_entry_by_slug` this ignores the published filter, because
    kb_propose has to see a prior rejection — that reason is the only channel
    by which a human's judgment reaches a future session. All requested
    statuses come back in ONE query: probing them separately cost three round
    trips, and only the `published` probe could use the partial unique indexes
    (`WHERE status='published'`) — the others fell back to scanning
    ix_kb_type_status.
    """
    stmt = (
        select(KnowledgeEntry)
        .where(
            KnowledgeEntry.type == type,
            func.lower(KnowledgeEntry.slug) == slug.lower(),
            _scope_key(repository_id),
            KnowledgeEntry.status.in_(statuses),
        )
        .options(defer(KnowledgeEntry.embedding))
        .order_by(KnowledgeEntry.id.asc())
    )
    # ascending id, so the last write per status wins
    return {entry.status: entry for entry in (await session.scalars(stmt)).all()}


async def update_entry(
    session: AsyncSession, entry_id: int, fields: dict
) -> KnowledgeEntry | None:
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        return None

    new_type = fields.get("type", entry.type)
    get_type(new_type)  # raises UnknownKbTypeError
    if "payload" in fields or "type" in fields:
        fields["payload"] = _validate_payload(
            new_type, fields.get("payload", entry.payload)
        )

    new_title = fields.get("title", entry.title)
    new_slug = fields.get("slug", entry.slug)
    new_repo = fields.get("repository_id", entry.repository_id)
    if fields.get("status", entry.status) == PUBLISHED:
        clash = await _collision(
            session,
            type=new_type,
            repository_id=new_repo,
            title=new_title,
            slug=new_slug,
            exclude_id=entry_id,
        )
        if clash is not None:
            raise DuplicateTermError(new_title, existing_id=clash)

    for key, value in fields.items():
        setattr(entry, key, value)
    if EMBEDDING_FIELDS & fields.keys():
        entry.embedding = None  # the kb enrich phase re-embeds edits
    # A retype can land a published entry on a type that numbers its entries.
    # set_status is the only other place that assigns one and it will never run
    # again on an already-published row, so without this the entry is
    # permanently unexportable ("no seq assigned") with no way back.
    if (
        entry.status == PUBLISHED
        and entry.seq is None
        and get_type(entry.type).assigns_seq
    ):
        entry.seq = await next_seq(session, entry.type, entry.repository_id)
    await _flush(session, new_title)
    return entry


async def delete_entry(session: AsyncSession, entry_id: int) -> bool:
    result = await session.execute(
        delete(KnowledgeEntry).where(KnowledgeEntry.id == entry_id)
    )
    return bool(result.rowcount)


async def set_status(
    session: AsyncSession,
    entry_id: int,
    status: str,
    *,
    replaces_id: int | None = None,
    reason: str | None = None,
) -> KnowledgeEntry | None:
    """The only path between statuses. Publishing is the uniqueness gate."""
    entry = await session.get(KnowledgeEntry, entry_id)
    if entry is None:
        return None
    allowed = TRANSITIONS.get(status)
    if allowed is None or entry.status not in allowed:
        raise InvalidTransitionError(entry.status, status)

    if status == PUBLISHED:
        incumbent_id = await _collision(
            session,
            type=entry.type,
            repository_id=entry.repository_id,
            title=entry.title,
            slug=entry.slug,
            exclude_id=entry.id,
        )
        if incumbent_id is not None:
            if replaces_id != incumbent_id:
                raise DuplicateTermError(entry.title, existing_id=incumbent_id)
            incumbent = await session.get(KnowledgeEntry, incumbent_id)
            incumbent.status = ARCHIVED
            await _flush(session, entry.title)
            # a title clash and a slug clash can live on different rows
            still = await _collision(
                session,
                type=entry.type,
                repository_id=entry.repository_id,
                title=entry.title,
                slug=entry.slug,
                exclude_id=entry.id,
            )
            if still is not None:
                raise DuplicateTermError(entry.title, existing_id=still)
        if entry.seq is None and get_type(entry.type).assigns_seq:
            entry.seq = await next_seq(session, entry.type, entry.repository_id)

    if status == REJECTED:
        entry.review_note = reason
    entry.status = status
    await _flush(session, entry.title)
    return entry


# ---- the lookup contract -------------------------------------------------


async def lookup(
    session: AsyncSession,
    term: str,
    *,
    type: str | None = None,
    repo_filter: RepoFilter = "*",
    embedder: EmbeddingClient | None = None,
) -> dict:
    """Deterministic lookup: exact title, exact slug, alias, then vector.

    Tiers 1 and 2 are the determinism guarantee and never change. Every tier
    is filtered to `published`, so a proposal is invisible here until a human
    publishes it.

    `also_matched` carries same-term hits in lower-precedence types. Callers
    MUST omit it when empty — `{match, results}` is the frozen top level of
    this response and two tests assert exact dict equality on the "none" case.
    """
    if type is not None:
        get_type(type)

    base = select(KnowledgeEntry).where(KnowledgeEntry.status == PUBLISHED)
    base = _scoped(base, repo_filter)
    if type is not None:
        base = base.where(KnowledgeEntry.type == type)

    # tier 1a — exact title
    hits = list(
        (
            await session.scalars(
                _ranked(
                    base.where(
                        func.lower(KnowledgeEntry.title) == term.lower(),
                        KnowledgeEntry.type.in_(types_with_lookup_key("title")),
                    )
                )
            )
        ).all()
    )
    # tier 1b — exact slug
    if not hits:
        hits = list(
            (
                await session.scalars(
                    _ranked(
                        base.where(
                            func.lower(KnowledgeEntry.slug) == term.lower(),
                            KnowledgeEntry.type.in_(types_with_lookup_key("slug")),
                        )
                    )
                )
            ).all()
        )
    if hits:
        return {"match": "exact", "results": [hits[0]], "also_matched": hits[1:]}

    # tier 2 — alias. Predicate text copied verbatim from the pre-typed query;
    # only conjunctive filters are added. Ordered by title, because slice 08
    # specified "if multiple entries alias-match, return all, ordered by term".
    alias_hits = list(
        (
            await session.scalars(
                base.where(
                    text(
                        "EXISTS (SELECT 1 FROM unnest(aliases) AS al "
                        "WHERE lower(al) = lower(:term))"
                    ).bindparams(term=term),
                    KnowledgeEntry.type.in_(types_with_lookup_key("aliases")),
                ).order_by(KnowledgeEntry.title, KnowledgeEntry.id)
            )
        ).all()
    )
    if alias_hits:
        return {"match": "alias", "results": alias_hits, "also_matched": []}

    # tier 3 — vector
    embedder = embedder or get_default_embedder()
    if embedder is not None:
        try:
            [query_vector] = await embedder.embed([term], input_type="query")
        except Exception:
            # a rate-limited lookup is otherwise indistinguishable from a term
            # the KB genuinely doesn't define
            logger.exception("kb vector lookup failed for %r", term)
            return {"match": "none", "results": [], "also_matched": []}
        vector_hits = list(
            (
                await session.scalars(
                    base.where(KnowledgeEntry.embedding.is_not(None))
                    .order_by(KnowledgeEntry.embedding.cosine_distance(query_vector))
                    .limit(VECTOR_LIMIT)
                )
            ).all()
        )
        if vector_hits:
            return {"match": "vector", "results": vector_hits, "also_matched": []}

    return {"match": "none", "results": [], "also_matched": []}


# ---- export --------------------------------------------------------------


async def entries_for_export(
    session: AsyncSession,
    type: str,
    repository_id: int,
    include_global: bool = True,
) -> list[KnowledgeEntry]:
    """Published entries of one type for one repo, global-shadowing applied.

    DISTINCT ON (lower(title)) with repo-scoped rows ordered first means a repo
    that overrides a shared term exports its own version and the term appears
    exactly once in CONTEXT.md. This lives here, not in KbType.export — the
    type layer stays DB-ignorant.
    """
    stmt = select(KnowledgeEntry).where(
        KnowledgeEntry.type == type, KnowledgeEntry.status == PUBLISHED
    )
    if include_global:
        stmt = stmt.where(
            or_(
                KnowledgeEntry.repository_id == repository_id,
                KnowledgeEntry.repository_id.is_(None),
            )
        )
    else:
        stmt = stmt.where(KnowledgeEntry.repository_id == repository_id)
    stmt = stmt.distinct(func.lower(KnowledgeEntry.title)).order_by(
        func.lower(KnowledgeEntry.title),
        KnowledgeEntry.repository_id.is_(None),
        KnowledgeEntry.slug,
        KnowledgeEntry.id,
    )
    # the exporter reads through KbEntryView, which has no embedding field
    stmt = stmt.options(defer(KnowledgeEntry.embedding))
    return list((await session.scalars(stmt)).all())
