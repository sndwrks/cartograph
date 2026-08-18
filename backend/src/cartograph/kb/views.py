"""The read-only projection the type layer sees.

Deliberately not the ORM model: `embed_text` and `export` must be pure and
testable with no database and no session attached.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from cartograph.models import KnowledgeEntry


@dataclass(frozen=True, slots=True)
class KbEntryView:
    id: int | None
    type: str
    slug: str
    title: str
    body: str
    aliases: tuple[str, ...]
    payload: dict[str, Any]
    status: str
    seq: int | None
    repository_id: int | None
    category: str | None
    created_at: datetime.datetime | None
    updated_at: datetime.datetime | None

    @classmethod
    def from_model(cls, entry: KnowledgeEntry) -> KbEntryView:
        return cls(
            id=entry.id,
            type=entry.type,
            slug=entry.slug,
            title=entry.title,
            body=entry.body,
            aliases=tuple(entry.aliases or ()),
            payload=dict(entry.payload or {}),
            status=entry.status,
            seq=entry.seq,
            repository_id=entry.repository_id,
            category=entry.category,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
