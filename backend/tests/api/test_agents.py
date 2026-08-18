from cartograph.query.agents import get_or_create_agent


async def test_create_and_duplicate(client):
    r = await client.post(
        "/api/v1/agents", json={"name": "claude", "role": "reviewer"}
    )
    assert r.status_code == 201
    assert r.json()["status"] == "idle"
    assert r.json()["last_seen"] is None

    assert (
        await client.post("/api/v1/agents", json={"name": "claude"})
    ).status_code == 409


async def test_status_update_bumps_last_seen(client):
    agent = (await client.post("/api/v1/agents", json={"name": "claude"})).json()
    r = await client.put(f"/api/v1/agents/{agent['id']}", json={"status": "busy"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "busy"
    assert body["last_seen"] is not None

    # updating without a status change keeps last_seen
    r2 = await client.put(f"/api/v1/agents/{agent['id']}", json={"role": "planner"})
    assert r2.json()["last_seen"] == body["last_seen"]


async def test_list_and_delete(client):
    a = (await client.post("/api/v1/agents", json={"name": "alpha"})).json()
    await client.post("/api/v1/agents", json={"name": "beta"})

    r = await client.get("/api/v1/agents")
    assert [x["name"] for x in r.json()["agents"]] == ["alpha", "beta"]

    assert (await client.delete(f"/api/v1/agents/{a['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/agents/{a['id']}")).status_code == 404
    assert (await client.delete(f"/api/v1/agents/{a['id']}")).status_code == 404


async def test_get_or_create_agent(session):
    first = await get_or_create_agent(session, "mcp-visitor")
    again = await get_or_create_agent(session, "mcp-visitor")
    assert first.id == again.id
    assert first.status == "idle"
