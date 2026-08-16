"""Read-only ingest-run status endpoints (slice 08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.api.schemas import IngestRunOut
from codegraph.db import get_session
from codegraph.query import ingest as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/ingest")


@router.get("/runs")
async def list_runs(
    session: SessionDep,
    repo: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    rows = await q.list_runs(session, repo_name=repo, limit=limit)
    if rows is None:
        raise HTTPException(status_code=404, detail="unknown repository")
    return {"runs": [IngestRunOut.from_run(run, name) for run, name in rows]}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, session: SessionDep) -> IngestRunOut:
    row = await q.get_run(session, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown run")
    run, name = row
    return IngestRunOut.from_run(run, name, include_error=True)
