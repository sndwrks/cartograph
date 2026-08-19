"""Message-board endpoints (slice 08)."""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.api.deps import no_unknown_query_params
from cartograph.api.schemas import MessageOut, ThreadRootOut
from cartograph.db import get_session
from cartograph.models import Node
from cartograph.query import messages as q
from cartograph.query.graph import (
    AmbiguousNodeNameError,
    NodeNameNotFoundError,
    resolve_node_by_name,
)
from cartograph.query.messages import UnknownRepositoryError

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/messages", dependencies=[Depends(no_unknown_query_params)])


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: int
    body: str
    subject: str | None = None
    thread_id: int | None = None
    node_id: int | None = None
    node_qualified_name: str | None = None
    repo: str | None = None

    @model_validator(mode="after")
    def _at_most_one_node_ref(self) -> MessageCreate:
        if self.node_id is not None and self.node_qualified_name is not None:
            raise ValueError("pass at most one of node_id or node_qualified_name")
        return self


def _ambiguous_detail(qualified_name: str, candidates: list[Node]) -> str:
    names = ", ".join(c.qualified_name for c in candidates)
    return f"ambiguous name {qualified_name!r} — candidates: {names}"


async def _resolve_node_id(
    session: AsyncSession, qualified_name: str, repo: str | None
) -> int:
    try:
        node = await resolve_node_by_name(session, qualified_name, repo)
    except NodeNameNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"no node found for {qualified_name!r}"
        )
    except AmbiguousNodeNameError as exc:
        raise HTTPException(
            status_code=409,
            detail=_ambiguous_detail(qualified_name, exc.candidates),
        )
    except UnknownRepositoryError:
        raise HTTPException(status_code=404, detail="unknown repository")
    return node.id


@router.post("", status_code=201)
async def create(body: MessageCreate, session: SessionDep) -> MessageOut:
    node_id = body.node_id
    if body.node_qualified_name is not None:
        node_id = await _resolve_node_id(session, body.node_qualified_name, body.repo)
    try:
        message = await q.create_message(
            session,
            agent_id=body.agent_id,
            body=body.body,
            subject=body.subject,
            thread_id=body.thread_id,
            node_id=node_id,
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
    node_qualified_name: str | None = None,
    agent_id: int | None = None,
    repo: str | None = None,
    since: datetime.datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    if node_id is not None and node_qualified_name is not None:
        raise HTTPException(
            status_code=422,
            detail="pass at most one of node_id or node_qualified_name",
        )
    if thread_id is not None:
        thread = await q.list_thread(session, thread_id)
        if thread is None:
            raise HTTPException(status_code=404, detail="unknown thread")
        return {"messages": [MessageOut.from_message(m) for m in thread]}
    if node_qualified_name is not None:
        node_id = await _resolve_node_id(session, node_qualified_name, repo)
    try:
        threads = await q.list_threads(
            session,
            node_id=node_id,
            agent_id=agent_id,
            repo_name=repo,
            limit=limit,
            offset=offset,
            since=since,
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
