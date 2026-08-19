import datetime

import pytest
from sqlalchemy import func, select

from cartograph.models import Node, NodeKind


@pytest.fixture
async def agent(client):
    r = await client.post("/api/v1/agents", json={"name": "poster"})
    return r.json()


async def post_message(client, agent, body, **extra):
    r = await client.post(
        "/api/v1/messages", json={"agent_id": agent["id"], "body": body, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_reply_to_reply_lands_on_root(client, agent):
    root = await post_message(client, agent, "root", subject="thread A")
    reply = await post_message(client, agent, "reply", thread_id=root["id"])
    nested = await post_message(client, agent, "nested", thread_id=reply["id"])
    assert reply["thread_id"] == root["id"]
    assert nested["thread_id"] == root["id"]  # rewritten to the root

    r = await client.get("/api/v1/messages", params={"thread_id": root["id"]})
    bodies = [m["body"] for m in r.json()["messages"]]
    assert bodies == ["root", "reply", "nested"]  # root first, replies oldest-first


async def test_root_listing_counts_and_order(client, agent):
    a = await post_message(client, agent, "first thread")
    await post_message(client, agent, "r1", thread_id=a["id"])
    await post_message(client, agent, "r2", thread_id=a["id"])
    b = await post_message(client, agent, "second thread")

    r = await client.get("/api/v1/messages")
    threads = r.json()["threads"]
    assert [t["message"]["body"] for t in threads] == ["second thread", "first thread"]
    by_body = {t["message"]["body"]: t for t in threads}
    assert by_body["first thread"]["reply_count"] == 2
    assert by_body["second thread"]["reply_count"] == 0
    assert all(t["last_activity"] is not None for t in threads)
    assert b["thread_id"] is None


async def test_node_filter_matches_reply_anchor(client, agent, seeded):
    anchored_root = await post_message(
        client, agent, "about save directly", node_id=seeded.save.id
    )
    plain_root = await post_message(client, agent, "unrelated root")
    await post_message(
        client, agent, "reply about save", thread_id=plain_root["id"],
        node_id=seeded.save.id,
    )
    await post_message(client, agent, "noise thread")

    r = await client.get("/api/v1/messages", params={"node_id": seeded.save.id})
    bodies = {t["message"]["body"] for t in r.json()["threads"]}
    # both the directly-anchored thread AND the one anchored via a reply
    assert bodies == {"about save directly", "unrelated root"}
    assert anchored_root["node_id"] == seeded.save.id


async def test_invalid_references_422(client, agent):
    bad = [
        {"agent_id": 999999, "body": "x"},
        {"agent_id": agent["id"], "body": "x", "thread_id": 999999},
        {"agent_id": agent["id"], "body": "x", "node_id": 999999},
    ]
    for payload in bad:
        assert (
            await client.post("/api/v1/messages", json=payload)
        ).status_code == 422, payload


async def test_posting_touches_agent_last_seen(client, agent):
    assert agent["last_seen"] is None
    await post_message(client, agent, "hello")
    r = await client.get(f"/api/v1/agents/{agent['id']}")
    assert r.json()["last_seen"] is not None


async def test_read_and_delete(client, agent):
    m = await post_message(client, agent, "to be deleted")
    assert (await client.get(f"/api/v1/messages/{m['id']}")).status_code == 200
    assert (await client.delete(f"/api/v1/messages/{m['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/messages/{m['id']}")).status_code == 404


async def test_node_qualified_name_resolves_on_post_and_get(client, agent, seeded):
    posted = await post_message(
        client, agent, "x", node_qualified_name="app.util.helper"
    )
    assert posted["node_id"] == seeded.helper.id

    r = await client.get(
        "/api/v1/messages", params={"node_qualified_name": "app.util.helper"}
    )
    bodies = {t["message"]["body"] for t in r.json()["threads"]}
    assert "x" in bodies


async def test_node_qualified_name_matching_nothing_is_404(client, agent):
    r = await client.post(
        "/api/v1/messages",
        json={
            "agent_id": agent["id"],
            "body": "x",
            "node_qualified_name": "does.not.Exist",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "no node found for 'does.not.Exist'"


async def test_ambiguous_bare_name_is_409_with_candidates(client, agent, seeded, session):
    session.add(
        Node(
            repository_id=seeded.repo.id,
            kind=NodeKind.function,
            name="helper",
            qualified_name="app.other.helper",
        )
    )
    await session.flush()

    r = await client.post(
        "/api/v1/messages",
        json={"agent_id": agent["id"], "body": "x", "node_qualified_name": "helper"},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "app.util.helper" in detail
    assert "app.other.helper" in detail


async def test_both_node_id_and_qualified_name_is_422_on_post(client, agent, seeded):
    r = await client.post(
        "/api/v1/messages",
        json={
            "agent_id": agent["id"],
            "body": "x",
            "node_id": seeded.helper.id,
            "node_qualified_name": "app.util.helper",
        },
    )
    assert r.status_code == 422


async def test_both_node_id_and_qualified_name_is_422_on_get(client, seeded):
    r = await client.get(
        "/api/v1/messages",
        params={"node_id": seeded.helper.id, "node_qualified_name": "app.util.helper"},
    )
    assert r.status_code == 422


async def test_undeclared_body_key_is_422_not_201(client, agent):
    r = await client.post(
        "/api/v1/messages",
        json={"agent_id": agent["id"], "body": "x", "node_name": "app.util.helper"},
    )
    assert r.status_code == 422


async def test_unknown_query_param_is_422_naming_the_key(client):
    r = await client.get("/api/v1/messages", params={"nod_id": 5})
    assert r.status_code == 422
    assert "nod_id" in r.json()["detail"]


async def test_since_filters_the_list(client, agent, session):
    await post_message(client, agent, "old news")
    now = await session.scalar(select(func.now()))

    past = (now - datetime.timedelta(hours=1)).isoformat()
    future = (now + datetime.timedelta(hours=1)).isoformat()

    r_past = await client.get("/api/v1/messages", params={"since": past})
    assert len(r_past.json()["threads"]) == 1

    r_future = await client.get("/api/v1/messages", params={"since": future})
    assert r_future.json()["threads"] == []
