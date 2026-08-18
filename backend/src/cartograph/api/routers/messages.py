"""Message-board endpoints (slice 08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.schemas import MessageOut, ThreadRootOut
from cartograph.db import get_session
from cartograph.query import messages as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/messages")


class MessageCreate(BaseModel):
    agent_id: int
    body: str
    subject: str | None = None
    thread_id: int | None = None
    node_id: int | None = None


@router.post("", status_code=201)
async def create(body: MessageCreate, session: SessionDep) -> MessageOut:
    try:
        message = await q.create_message(
            session,
            agent_id=body.agent_id,
            body=body.body,
            subject=body.subject,
            thread_id=body.thread_id,
            node_id=body.node_id,
        )
    except q.InvalidReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
    return MessageOut.from_message(message)


@router.get("")
async def list_(
    session: SessionDep,
    thread_id: int | None = None,
    node_id: int | None = None,
    agent_id: int | None = None,
    repo: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    if thread_id is not None:
        thread = await q.list_thread(session, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="unknown thread")
        return {"messages": [MessageOut.from_message(m) for m in thread]}
    try:
        threads = await q.list_threads(
            session,
            node_id=node_id,
            agent_id=agent_id,
            repo_name=repo,
            limit=limit,
            offset=offset,
        )
    except q.UnknownRepositoryError:
        raise HTTPException(status_code=404, detail="unknown repository")
    return {
        "threads": [
            ThreadRootOut(
                message=MessageOut.from_message(root),
                reply_count=count,
                last_activity=last,
            )
            for root, count, last in threads
        ]
    }


@router.get("/{message_id}")
async def read(message_id: int, session: SessionDep) -> MessageOut:
    message = await q.get_message(session, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="unknown message")
    return MessageOut.from_message(message)


@router.delete("/{message_id}", status_code=204)
async def delete(message_id: int, session: SessionDep) -> None:
    if not await q.delete_message(session, message_id):
        raise HTTPException(status_code=404, detail="unknown message")
    await session.commit()
