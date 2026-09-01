"""Aggregates over tool_calls for the usage dashboard.

Everything is SQL — sums, filters, date_trunc — so the summary is a handful
of round trips regardless of history size. Repo scoping includes unscoped
rows (repository_id IS NULL): a call that named no repository belongs to
every repository's view, and `unscoped_calls` tells the reader how many of
the total those are.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Repository, ToolCall
from cartograph.query.ingest import get_repository_by_name

Window = Literal["24h", "7d", "30d", "all"]
WINDOWS: dict[str, datetime.timedelta | None] = {
    "24h": datetime.timedelta(hours=24),
    "7d": datetime.timedelta(days=7),
    "30d": datetime.timedelta(days=30),
    "all": None,
}


def _plain(row) -> dict:
    """RowMapping -> dict with SQL numerics (Decimal from sum/avg) as Python
    ints/floats, so the schema layer can do arithmetic on them."""
    out = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal):
            out[key] = int(value) if value == value.to_integral_value() else float(value)
        else:
            out[key] = value
    return out


def _since(window: str, now: datetime.datetime | None = None) -> datetime.datetime | None:
    span = WINDOWS[window]
    if span is None:
        return None
    return (now or datetime.datetime.now(datetime.UTC)) - span


def _scoped(stmt, repository_id: int | None, since: datetime.datetime | None):
    if repository_id is not None:
        stmt = stmt.where(
            or_(ToolCall.repository_id == repository_id, ToolCall.repository_id.is_(None))
        )
    if since is not None:
        stmt = stmt.where(ToolCall.started_at >= since)
    return stmt


async def _resolve(session: AsyncSession, repo_name: str | None) -> int | None | Literal[False]:
    """repository id, None for "every repository", False for unknown."""
    if repo_name is None:
        return None
    repo = await get_repository_by_name(session, repo_name)
    return repo.id if repo is not None else False


async def summary(
    session: AsyncSession,
    repo_name: str | None,
    window: str,
    now: datetime.datetime | None = None,
) -> dict | None:
    """None = unknown repository. Sizes are bytes; the schema layer turns
    them into token estimates."""
    repository_id = await _resolve(session, repo_name)
    if repository_id is False:
        return None
    since = _since(window, now)
    has_baseline = ToolCall.baseline_bytes.is_not(None)

    totals_stmt = _scoped(
        select(
            func.count().label("calls"),
            func.count().filter(ToolCall.ok.is_(False)).label("errors"),
            func.count().filter(ToolCall.repository_id.is_(None)).label("unscoped_calls"),
            func.count(func.distinct(ToolCall.agent_name)).label("agents"),
            func.coalesce(func.sum(ToolCall.response_bytes), 0).label("response_bytes"),
            func.coalesce(func.sum(ToolCall.request_bytes), 0).label("request_bytes"),
            func.count().filter(has_baseline).label("baseline_calls"),
            func.coalesce(func.sum(ToolCall.baseline_bytes).filter(has_baseline), 0).label(
                "baseline_bytes"
            ),
            # like-for-like: response bytes over the same rows the baseline covers
            func.coalesce(
                func.sum(ToolCall.response_bytes).filter(has_baseline), 0
            ).label("baseline_response_bytes"),
            func.coalesce(func.sum(ToolCall.baseline_files).filter(has_baseline), 0).label(
                "baseline_files"
            ),
        ),
        repository_id,
        since,
    )
    totals = (await session.execute(totals_stmt)).mappings().one()

    by_tool_stmt = _scoped(
        select(
            ToolCall.tool,
            func.count().label("calls"),
            func.count().filter(ToolCall.ok.is_(False)).label("errors"),
            func.avg(ToolCall.duration_ms).label("avg_duration_ms"),
            func.percentile_cont(0.5)
            .within_group(ToolCall.duration_ms)
            .label("p50_duration_ms"),
            func.coalesce(func.sum(ToolCall.response_bytes), 0).label("response_bytes"),
            func.coalesce(func.sum(ToolCall.baseline_bytes), 0).label("baseline_bytes"),
        ),
        repository_id,
        since,
    ).group_by(ToolCall.tool).order_by(func.count().desc(), ToolCall.tool)
    by_tool = (await session.execute(by_tool_stmt)).mappings().all()

    bucket = "hour" if window == "24h" else "day"
    # explicit UTC: two-argument date_trunc truncates in the session TimeZone,
    # and the SPA aligns its grid to UTC boundaries
    start = func.date_trunc(bucket, ToolCall.started_at, "UTC").label("start")
    buckets_stmt = _scoped(
        select(
            start,
            func.count().label("calls"),
            func.count().filter(ToolCall.ok.is_(False)).label("errors"),
            func.coalesce(func.sum(ToolCall.response_bytes), 0).label("response_bytes"),
            func.coalesce(func.sum(ToolCall.baseline_bytes), 0).label("baseline_bytes"),
            # the chart pairs this with baseline_bytes — same rows on both
            # sides, as in totals, or a kb-heavy day reads as a loss
            func.coalesce(
                func.sum(ToolCall.response_bytes).filter(has_baseline), 0
            ).label("baseline_response_bytes"),
        ),
        repository_id,
        since,
    ).group_by(start).order_by(start)
    buckets = (await session.execute(buckets_stmt)).mappings().all()

    agents_stmt = (
        _scoped(
            select(
                ToolCall.agent_name.label("name"),
                func.count().label("calls"),
                func.count().filter(ToolCall.ok.is_(False)).label("errors"),
                func.max(ToolCall.started_at).label("last_call"),
            ),
            repository_id,
            since,
        )
        .where(ToolCall.agent_name.is_not(None))
        .group_by(ToolCall.agent_name)
        .order_by(func.count().desc(), ToolCall.agent_name)
    )
    agents = (await session.execute(agents_stmt)).mappings().all()

    return {
        "window": window,
        "bucket": bucket,
        "totals": _plain(totals),
        "by_tool": [_plain(r) for r in by_tool],
        "buckets": [_plain(r) for r in buckets],
        "agents": [_plain(r) for r in agents],
    }


async def list_calls(
    session: AsyncSession,
    repo_name: str | None,
    tool: str | None = None,
    agent: str | None = None,
    limit: int = 50,
    before: int | None = None,
    window: str = "30d",
    now: datetime.datetime | None = None,
) -> list[tuple[ToolCall, str | None]] | None:
    """Newest first, keyset-paged by id, bounded to `window` so a filter on a
    rarely-used tool cannot walk the whole table. None = unknown repository."""
    repository_id = await _resolve(session, repo_name)
    if repository_id is False:
        return None
    stmt = _scoped(
        select(ToolCall, Repository.name).outerjoin(
            Repository, ToolCall.repository_id == Repository.id
        ),
        repository_id,
        _since(window, now),
    )
    if tool is not None:
        stmt = stmt.where(ToolCall.tool == tool)
    if agent is not None:
        stmt = stmt.where(ToolCall.agent_name == agent)
    if before is not None:
        stmt = stmt.where(ToolCall.id < before)
    rows = await session.execute(stmt.order_by(ToolCall.id.desc()).limit(limit))
    return [(call, name) for call, name in rows.all()]
