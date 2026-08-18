"""Message-board queries: flat threading with node anchoring (slice 08)."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from cartograph.models import Agent, AgentMessage, Node
from cartograph.query.agents import touch_agent
from cartograph.query.ingest import get_repository_by_name


class InvalidReferenceError(ValueError):
    pass


class UnknownRepositoryError(LookupError):
    pass


async def create_message(
    session: AsyncSession,
    agent_id: int,
    body: str,
    subject: str | None = None,
    thread_id: int | None = None,
    node_id: int | None = None,
) -> AgentMessage:
    if await session.get(Agent, agent_id) is None:
        raise InvalidReferenceError(f"unknown agent {agent_id}")
    if node_id is not None and await session.get(Node, node_id) is None:
        raise InvalidReferenceError(f"unknown node {node_id}")
    if thread_id is not None:
        target = await session.get(AgentMessage, thread_id)
        if target is None:
            raise InvalidReferenceError(f"unknown thread {thread_id}")
        # replies to a reply land on the root: threading stays flat
        if target.thread_id is not None:
            thread_id = target.thread_id

    message = AgentMessage(
        agent_id=agent_id,
        body=body,
        subject=subject,
        thread_id=thread_id,
        node_id=node_id,
    )
    session.add(message)
    await session.flush()
    await touch_agent(session, agent_id)
    return message


def _root_id_expr():
    return func.coalesce(AgentMessage.thread_id, AgentMessage.id)


async def list_threads(
    session: AsyncSession,
    node_id: int | None = None,
    agent_id: int | None = None,
    repo_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
    since: object | None = None,
) -> list[tuple[AgentMessage, int, object]]:
    """Thread roots newest-first as (root, reply_count, last_activity)."""
    replies = aliased(AgentMessage)
    stmt = (
        select(
            AgentMessage,
            func.count(replies.id),
            func.greatest(
                AgentMessage.created_at, func.max(replies.created_at)
            ).label("last_activity"),
        )
        .outerjoin(replies, replies.thread_id == AgentMessage.id)
        .where(AgentMessage.thread_id.is_(None))
        .group_by(AgentMessage.id)
        .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if node_id is not None:
        # threads whose root OR any reply is anchored to the node
        anchored_roots = select(_root_id_expr()).where(AgentMessage.node_id == node_id)
        stmt = stmt.where(AgentMessage.id.in_(anchored_roots))
    if agent_id is not None:
        by_agent = select(_root_id_expr()).where(AgentMessage.agent_id == agent_id)
        stmt = stmt.where(AgentMessage.id.in_(by_agent))
    if repo_name is not None:
        repo = await get_repository_by_name(session, repo_name)
        if repo is None:
            raise UnknownRepositoryError(repo_name)
        # A message reaches a repository only through its anchor node, so a
        # thread belongs to a repo if the root or any reply is anchored there.
        in_repo = (
            select(_root_id_expr())
            .join(Node, Node.id == AgentMessage.node_id)
            .where(Node.repository_id == repo.id)
        )
        # Unanchored threads have no repository at all. They are kept visible in
        # every repo rather than dropped — filtering them out would make them
        # unreachable from the UI entirely, with no view that could ever show
        # them. (Note node_id is ON DELETE SET NULL, so a re-ingest that removes
        # a node turns its threads into this kind.)
        anchored_anywhere = select(_root_id_expr()).where(
            AgentMessage.node_id.is_not(None)
        )
        stmt = stmt.where(
            or_(
                AgentMessage.id.in_(in_repo),
                AgentMessage.id.not_in(anchored_anywhere),
            )
        )
    if since is not None:
        stmt = stmt.where(AgentMessage.created_at >= since)
    return [(root, count, last) for root, count, last in (await session.execute(stmt)).all()]


async def list_thread(
    session: AsyncSession, thread_id: int
) -> list[AgentMessage] | None:
    """Root + replies oldest-first; a reply id resolves to its root's thread."""
    root = await session.get(AgentMessage, thread_id)
    if root is None:
        return None
    if root.thread_id is not None:
        root = await session.get(AgentMessage, root.thread_id)
        if root is None:
            return None
    replies = (
        await session.scalars(
            select(AgentMessage)
            .where(AgentMessage.thread_id == root.id)
            .order_by(AgentMessage.created_at, AgentMessage.id)
        )
    ).all()
    return [root, *replies]


async def get_message(session: AsyncSession, message_id: int) -> AgentMessage | None:
    return await session.get(AgentMessage, message_id)


async def delete_message(session: AsyncSession, message_id: int) -> bool:
    result = await session.execute(
        delete(AgentMessage).where(AgentMessage.id == message_id)
    )
    return bool(result.rowcount)
