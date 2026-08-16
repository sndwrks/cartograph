"""Agent registry queries (slice 08)."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.models import Agent


class DuplicateAgentError(ValueError):
    pass


async def create_agent(
    session: AsyncSession,
    name: str,
    role: str | None = None,
    metadata_json: dict | None = None,
) -> Agent:
    if await session.scalar(select(Agent.id).where(Agent.name == name)) is not None:
        raise DuplicateAgentError(name)
    agent = Agent(name=name, role=role, metadata_json=metadata_json)
    session.add(agent)
    await session.flush()
    return agent


async def list_agents(session: AsyncSession) -> list[Agent]:
    return list((await session.scalars(select(Agent).order_by(Agent.name))).all())


async def get_agent(session: AsyncSession, agent_id: int) -> Agent | None:
    return await session.get(Agent, agent_id)


async def get_or_create_agent(session: AsyncSession, name: str) -> Agent:
    """Existing agent by name, or a fresh one with defaults (MCP self-registration)."""
    agent = await session.scalar(select(Agent).where(Agent.name == name))
    if agent is None:
        agent = Agent(name=name)
        session.add(agent)
        await session.flush()
    return agent


async def update_agent(
    session: AsyncSession, agent_id: int, fields: dict
) -> Agent | None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return None
    if "status" in fields and fields["status"] != agent.status:
        agent.last_seen = await session.scalar(select(func.now()))
    for key, value in fields.items():
        setattr(agent, key, value)
    await session.flush()
    return agent


async def touch_agent(session: AsyncSession, agent_id: int) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is not None:
        agent.last_seen = await session.scalar(select(func.now()))
        await session.flush()


async def delete_agent(session: AsyncSession, agent_id: int) -> bool:
    result = await session.execute(delete(Agent).where(Agent.id == agent_id))
    return bool(result.rowcount)
