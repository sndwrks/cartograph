"""Usage dashboard endpoints: aggregates and recent calls over tool_calls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.schemas import ToolCallOut, UsageSummaryOut
from cartograph.config import get_settings
from cartograph.db import get_session
from cartograph.query import usage as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/usage")


@router.get("/summary")
async def usage_summary(
    session: SessionDep,
    repo: str | None = None,
    window: q.Window = "7d",
) -> UsageSummaryOut:
    result = await q.summary(session, repo, window)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown repository")
    return UsageSummaryOut.from_query(result, get_settings().USAGE_CHARS_PER_TOKEN)


@router.get("/calls")
async def usage_calls(
    session: SessionDep,
    repo: str | None = None,
    tool: str | None = None,
    agent: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: int | None = None,
    window: q.Window = "30d",
) -> dict:
    rows = await q.list_calls(
        session, repo, tool=tool, agent=agent, limit=limit, before=before, window=window
    )
    if rows is None:
        raise HTTPException(status_code=404, detail="unknown repository")
    return {"calls": [ToolCallOut.from_call(call, name) for call, name in rows]}
