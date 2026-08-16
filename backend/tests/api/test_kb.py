async def make(client, term, definition, **extra):
    r = await client.post("/api/v1/kb", json={"term": term, "definition": definition, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_psn_lookup_is_deterministic(client):
    await make(client, "PSN", "PositageNet — never any other expansion")
    await make(
        client,
        "PlayStation",
        "Sony console; its playstation network is abbreviated psn by fans",
    )

    for query in ("PSN", "psn", "Psn"):
        r = await client.get("/api/v1/kb/lookup", params={"term": query})
        assert r.status_code == 200
        body = r.json()
        assert body["match"] == "exact"
        assert len(body["results"]) == 1
        assert body["results"][0]["definition"].startswith("PositageNet")


async def test_alias_lookup(client):
    await make(client, "PSN", "PositageNet", aliases=["POS-NET", "positage"])
    r = await client.get("/api/v1/kb/lookup", params={"term": "pos-net"})
    body = r.json()
    assert body["match"] == "alias"
    assert [e["term"] for e in body["results"]] == ["PSN"]


async def test_unknown_term_lookup(client):
    r = await client.get("/api/v1/kb/lookup", params={"term": "nonexistent"})
    assert r.status_code == 200
    assert r.json() == {"match": "none", "results": []}


async def test_duplicate_term_409(client):
    await make(client, "PSN", "PositageNet")
    r = await client.post("/api/v1/kb", json={"term": "psn", "definition": "dupe"})
    assert r.status_code == 409


async def test_crud_roundtrip(client):
    entry = await make(client, "DDD", "domain driven design", category="acronym")
    entry_id = entry["id"]

    r = await client.get(f"/api/v1/kb/{entry_id}")
    assert r.json()["term"] == "DDD"

    r = await client.put(
        f"/api/v1/kb/{entry_id}", json={"definition": "Domain-Driven Design"}
    )
    assert r.status_code == 200
    assert r.json()["definition"] == "Domain-Driven Design"

    r = await client.get("/api/v1/kb", params={"category": "acronym"})
    assert [e["term"] for e in r.json()["entries"]] == ["DDD"]
    r = await client.get("/api/v1/kb", params={"category": "domain"})
    assert r.json()["entries"] == []

    assert (await client.delete(f"/api/v1/kb/{entry_id}")).status_code == 204
    assert (await client.get(f"/api/v1/kb/{entry_id}")).status_code == 404


async def test_update_term_collision_409(client):
    await make(client, "PSN", "PositageNet")
    other = await make(client, "ABC", "alphabet")
    r = await client.put(f"/api/v1/kb/{other['id']}", json={"term": "psn"})
    assert r.status_code == 409
