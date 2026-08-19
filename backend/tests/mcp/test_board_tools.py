import datetime

import pytest
from sqlalchemy import func, select

from cartograph.mcp_server import tools
from cartograph.models import Agent, AgentMessage, Node, NodeKind, Repository
from cartograph.query.graph import (
    AmbiguousNodeNameError,
    NodeNameNotFoundError,
    resolve_node_by_name,
)
from cartograph.query.messages import UnknownRepositoryError


async def test_post_message_self_registers(session, seeded):
    result = await tools.post_message(
        session, "scout-1", "Investigating save()", subject="save audit"
    )
    assert "error" not in result
    assert result["agent"] == "scout-1"
    assert result["thread_id"] is None  # a root

    agent = await session.scalar(select(Agent).where(Agent.name == "scout-1"))
    assert agent is not None
    assert agent.last_seen is not None

    # posting again reuses the agent
    await tools.post_message(session, "scout-1", "still looking")
    count = await session.scalar(
        select(func.count()).select_from(Agent).where(Agent.name == "scout-1")
    )
    assert count == 1


async def test_reply_to_reply_lands_on_root(session, seeded):
    root = await tools.post_message(session, "a1", "root")
    reply = await tools.post_message(session, "a1", "reply", thread_id=root["id"])
    nested = await tools.post_message(session, "a2", "nested", thread_id=reply["id"])
    assert reply["thread_id"] == root["id"]
    assert nested["thread_id"] == root["id"]

    thread = await tools.read_board(session, thread_id=root["id"])
    assert [m["body"] for m in thread["messages"]] == ["root", "reply", "nested"]
    assert [m["agent"] for m in thread["messages"]] == ["a1", "a1", "a2"]


async def test_read_board_by_node_anchor(session, seeded):
    await tools.post_message(
        session,
        "scout-1",
        "save() has a name_match edge worth checking",
        subject="save caution",
        node_qualified_name="app.services.OrderService.save",
    )
    await tools.post_message(session, "scout-1", "unrelated chatter")

    board = await tools.read_board(
        session, node_qualified_name="app.services.OrderService.save"
    )
    assert len(board["threads"]) == 1
    thread = board["threads"][0]
    assert thread["subject"] == "save caution"
    assert thread["node_id"] == seeded.save.id
    assert thread["reply_count"] == 0

    everything = await tools.read_board(session)
    assert len(everything["threads"]) == 2  # newest first
    assert everything["threads"][0]["body"] == "unrelated chatter"


async def test_since_filter(session, seeded):
    await tools.post_message(session, "a1", "old news")
    now = await session.scalar(select(func.now()))

    past = (now - datetime.timedelta(hours=1)).isoformat()
    future = (now + datetime.timedelta(hours=1)).isoformat()
    assert len((await tools.read_board(session, since=past))["threads"]) == 1
    assert (await tools.read_board(session, since=future))["threads"] == []
    assert "error" in await tools.read_board(session, since="not-a-date")


async def test_bad_node_name_errors(session, seeded):
    missing = await tools.post_message(
        session, "a1", "x", node_qualified_name="does.not.Exist"
    )
    assert "error" in missing and "candidates" not in missing

    session.add(
        Node(
            repository_id=seeded.repo.id,
            kind=NodeKind.function,
            name="helper",
            qualified_name="app.other.helper",
        )
    )
    await session.flush()
    ambiguous = await tools.post_message(
        session, "a1", "x", node_qualified_name="helper"
    )
    assert "error" in ambiguous
    assert {c["qualified_name"] for c in ambiguous["candidates"]} == {
        "app.util.helper",
        "app.other.helper",
    }


async def test_read_board_agent_filter(session, seeded):
    await tools.post_message(session, "alpha", "from alpha")
    await tools.post_message(session, "beta", "from beta")
    board = await tools.read_board(session, agent_name="alpha")
    assert [t["body"] for t in board["threads"]] == ["from alpha"]
    assert (await tools.read_board(session, agent_name="nobody"))["threads"] == []


# --- slice 19: repo parity on post_message/read_board, and the relocated
# resolver's raise behaviour (query/graph.py:resolve_node_by_name) ---------


async def test_post_message_repo_scopes_anchor(session, seeded):
    result = await tools.post_message(
        session, "a1", "x", node_qualified_name="app.util.helper", repo="seeded"
    )
    assert "error" not in result
    assert result["node_id"] == seeded.helper.id


async def test_post_message_unknown_repo_errors_and_writes_nothing(session, seeded):
    before = await session.scalar(select(func.count()).select_from(AgentMessage))
    result = await tools.post_message(
        session, "a1", "x", node_qualified_name="app.util.helper", repo="other"
    )
    assert "error" in result
    after = await session.scalar(select(func.count()).select_from(AgentMessage))
    assert after == before


async def test_read_board_repo_scopes_to_anchored_threads(session, seeded):
    other_repo = Repository(name="other-repo", root_path="/repos/other")
    session.add(other_repo)
    await session.flush()
    other_node = Node(
        repository_id=other_repo.id,
        kind=NodeKind.function,
        name="thing",
        qualified_name="other.thing",
    )
    session.add(other_node)
    await session.flush()

    await tools.post_message(
        session,
        "a1",
        "seeded anchor",
        node_qualified_name="app.util.helper",
        repo="seeded",
    )
    await tools.post_message(
        session,
        "a1",
        "other anchor",
        node_qualified_name="other.thing",
        repo="other-repo",
    )
    await tools.post_message(session, "a1", "unanchored")

    board = await tools.read_board(session, repo="seeded")
    bodies = {t["body"] for t in board["threads"]}
    assert bodies == {"seeded anchor", "unanchored"}  # unanchored stays visible everywhere


async def test_read_board_unknown_repo_errors(session, seeded):
    result = await tools.read_board(session, repo="nope")
    assert "error" in result


async def test_resolve_node_by_name_not_found(session, seeded):
    with pytest.raises(NodeNameNotFoundError):
        await resolve_node_by_name(session, "does.not.Exist")


async def test_resolve_node_by_name_ambiguous(session, seeded):
    session.add(
        Node(
            repository_id=seeded.repo.id,
            kind=NodeKind.function,
            name="helper",
            qualified_name="app.other.helper",
        )
    )
    await session.flush()
    with pytest.raises(AmbiguousNodeNameError) as exc_info:
        await resolve_node_by_name(session, "helper")
    assert {c.qualified_name for c in exc_info.value.candidates} == {
        "app.util.helper",
        "app.other.helper",
    }


async def test_resolve_node_by_name_repo_scoping(session, seeded):
    node = await resolve_node_by_name(session, "app.util.helper", repo="seeded")
    assert node.id == seeded.helper.id

    with pytest.raises(UnknownRepositoryError):
        await resolve_node_by_name(session, "app.util.helper", repo="other")
