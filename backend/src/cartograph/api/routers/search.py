"""Search endpoint (slice 07)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.db import get_session
from cartograph.models import NodeKind
from cartograph.query import search as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter()

_VALID_KINDS = {k.value for k in NodeKind if k != NodeKind.file}


def _parse_kinds(kinds: str | None) -> list[str] | None:
    if not kinds:
        return None
    parsed = [k.strip() for k in kinds.split(",") if k.strip()]
    invalid = [k for k in parsed if k not in _VALID_KINDS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid kinds: {invalid}")
    return parsed or None


@router.get("/search")
async def search(
    q_: Annotated[str, Query(alias="q", min_length=1)],
    session: SessionDep,
    repo: str | None = None,
    mode: Literal["text", "semantic", "hybrid"] = "hybrid",
    kinds: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    kind_list = _parse_kinds(kinds)
    try:
        if mode == "semantic":
            try:
                results = await q.search_semantic(
                    session, repo, q_, kind_list, limit
                )
            except NotImplementedError as exc:
                raise HTTPException(status_code=501, detail=str(exc))
            return {"results": results}
        if mode == "text":
            results = await q.search_text(session, repo, q_, kind_list, limit)
            return {"results": results}
        results, degraded = await q.search_hybrid(session, repo, q_, kind_list, limit)
        # the degraded flag only appears while hybrid is text-only
        return {"results": results, **({"degraded": True} if degraded else {})}
    except q.UnknownRepositoryError:
        raise HTTPException(status_code=404, detail="unknown repository")
