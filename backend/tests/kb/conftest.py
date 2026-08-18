"""Fixtures for the DB-free KB type layer."""

import datetime

import pytest

from cartograph.kb.types import ExportContext
from cartograph.kb.views import KbEntryView


def make_view(
    type: str,
    slug: str,
    title: str,
    body: str = "A body.",
    *,
    payload: dict | None = None,
    aliases: tuple[str, ...] = (),
    seq: int | None = None,
    status: str = "published",
    repository_id: int | None = None,
    entry_id: int = 1,
) -> KbEntryView:
    return KbEntryView(
        id=entry_id,
        type=type,
        slug=slug,
        title=title,
        body=body,
        aliases=aliases,
        payload=payload or {},
        status=status,
        seq=seq,
        repository_id=repository_id,
        category=None,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )


@pytest.fixture
def view():
    return make_view


@pytest.fixture
def ctx():
    return ExportContext(
        repository_name="acme",
        context_name="Acme",
        context_description="The ordering system.",
    )
