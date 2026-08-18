"""Agent registry endpoints (slice 08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.schemas import AgentOut
from cartograph.db import get_session
from cartograph.query import agents as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/agents")


class AgentCreate(BaseModel):
    name: str
    role: str | None = None
    metadata_json: dict | None = None


class AgentUpdate(BaseModel):
    role: str | None = None
    status: str | None = None
    metadata_json: dict | None = None


@router.post("", status_code=201)
async def create(body: AgentCreate, session: SessionDep) -> AgentOut:
    try:
        agent = await q.create_agent(session, body.name, body.role, body.metadata_json)
    except q.DuplicateAgentError as exc:
        raise HTTPException(status_code=409, detail=f"agent already exists: {exc}")
    await session.commit()
    return AgentOut.from_agent(agent)


@router.get("")
async def list_(session: SessionDep) -> dict:
    return {"agents": [AgentOut.from_agent(a) for a in await q.list_agents(session)]}


@router.get("/{agent_id}")
async def read(agent_id: int, session: SessionDep) -> AgentOut:
    agent = await q.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return AgentOut.from_agent(agent)


@router.put("/{agent_id}")
async def update(agent_id: int, body: AgentUpdate, session: SessionDep) -> AgentOut:
    agent = await q.update_agent(session, agent_id, body.model_dump(exclude_unset=True))
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    await session.commit()
    return AgentOut.from_agent(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete(agent_id: int, session: SessionDep) -> None:
    if not await q.delete_agent(session, agent_id):
        raise HTTPException(status_code=404, detail="unknown agent")
    await session.commit()
