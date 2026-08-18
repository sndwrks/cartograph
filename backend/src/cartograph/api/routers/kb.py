"""Knowledge-base endpoints (slice 08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.schemas import KBEntryOut
from cartograph.db import get_session
from cartograph.query import kb as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/kb")


class KBCreate(BaseModel):
    term: str
    definition: str
    aliases: list[str] | None = None
    category: str | None = None  # acronym | domain | convention


class KBUpdate(BaseModel):
    term: str | None = None
    definition: str | None = None
    aliases: list[str] | None = None
    category: str | None = None


@router.post("", status_code=201)
async def create(body: KBCreate, session: SessionDep) -> KBEntryOut:
    try:
        entry = await q.create_entry(
            session, body.term, body.definition, body.aliases, body.category
        )
    except q.DuplicateTermError as exc:
        raise HTTPException(status_code=409, detail=f"term already exists: {exc}")
    await session.commit()
    return KBEntryOut.from_entry(entry)


@router.get("")
async def list_(
    session: SessionDep,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    entries = await q.list_entries(session, category, limit, offset)
    return {"entries": [KBEntryOut.from_entry(e) for e in entries]}


@router.get("/lookup")
async def lookup(term: Annotated[str, Query(min_length=1)], session: SessionDep) -> dict:
    result = await q.lookup(session, term)
    return {
        "match": result["match"],
        "results": [KBEntryOut.from_entry(e) for e in result["results"]],
    }


@router.get("/{entry_id}")
async def read(entry_id: int, session: SessionDep) -> KBEntryOut:
    entry = await q.get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown kb entry")
    return KBEntryOut.from_entry(entry)


@router.put("/{entry_id}")
async def update(entry_id: int, body: KBUpdate, session: SessionDep) -> KBEntryOut:
    try:
        entry = await q.update_entry(
            session, entry_id, body.model_dump(exclude_unset=True)
        )
    except q.DuplicateTermError as exc:
        raise HTTPException(status_code=409, detail=f"term already exists: {exc}")
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown kb entry")
    await session.commit()
    # updated_at is a server-side onupdate default: refresh it explicitly, a
    # lazy attribute load would attempt sync IO on the async connection
    await session.refresh(entry)
    return KBEntryOut.from_entry(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete(entry_id: int, session: SessionDep) -> None:
    if not await q.delete_entry(session, entry_id):
        raise HTTPException(status_code=404, detail="unknown kb entry")
    await session.commit()
