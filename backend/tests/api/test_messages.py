import pytest


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
