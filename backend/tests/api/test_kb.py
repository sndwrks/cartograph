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


# ---- typed KB (slice 15) -------------------------------------------------


async def make_typed(client, type, title, body, **extra):
    r = await client.post(
        "/api/v1/kb", json={"type": type, "title": title, "body": body, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_psn_determinism_survives_same_title_in_another_type(client):
    """A runbook may be titled PSN; the glossary term still wins, alone."""
    await make(client, "PSN", "PositageNet — never any other expansion")
    await make_typed(client, "runbook", "PSN", "How to restart PSN.")

    r = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    body = r.json()
    assert body["match"] == "exact"
    assert len(body["results"]) == 1
    assert body["results"][0]["type"] == "glossary"
    assert body["results"][0]["definition"].startswith("PositageNet")
    assert [e["type"] for e in body["also_matched"]] == ["runbook"]


async def test_lookup_type_scoped_returns_that_type(client):
    await make(client, "PSN", "PositageNet")
    await make_typed(client, "runbook", "PSN", "How to restart PSN.")

    r = await client.get("/api/v1/kb/lookup", params={"term": "psn", "type": "runbook"})
    body = r.json()
    assert body["match"] == "exact"
    assert body["results"][0]["type"] == "runbook"
    assert "also_matched" not in body


async def test_create_typed_entry_with_payload(client):
    entry = await make_typed(
        client,
        "decision",
        "Flat threads",
        "Replies re-parent to the root.",
        payload={"context": "Threads nested arbitrarily.", "decision_status": "accepted"},
    )
    assert entry["payload"]["context"] == "Threads nested arbitrarily."
    assert entry["slug"] == "flat-threads"


async def test_create_rejects_unknown_type_422(client):
    r = await client.post(
        "/api/v1/kb", json={"type": "adr", "title": "X", "body": "Y"}
    )
    assert r.status_code == 422


async def test_create_rejects_invalid_payload_422(client):
    r = await client.post(
        "/api/v1/kb",
        json={
            "type": "decision",
            "title": "X",
            "body": "Y",
            "payload": {"decision_status": "maybe"},
        },
    )
    assert r.status_code == 422


async def test_slug_derived_from_title_when_omitted(client):
    entry = await make_typed(client, "convention", "Branch Names!", "Prefix with main.")
    assert entry["slug"] == "branch-names"


async def test_duplicate_slug_same_type_409(client):
    await make_typed(client, "runbook", "Rotate key", "…", slug="rotate")
    r = await client.post(
        "/api/v1/kb",
        json={"type": "runbook", "title": "Something else", "body": "…", "slug": "rotate"},
    )
    assert r.status_code == 409


async def test_same_slug_different_type_allowed(client):
    await make_typed(client, "runbook", "Rotate key", "…", slug="rotate")
    await make_typed(client, "convention", "Rotation policy", "…", slug="rotate")


async def test_kb_types_endpoint_lists_registry(client):
    """Also guards the path ordering: /types must resolve before /{entry_id}."""
    r = await client.get("/api/v1/kb/types")
    assert r.status_code == 200
    types = {t["name"]: t for t in r.json()["types"]}
    assert set(types) == {
        "glossary", "specification", "decision", "convention", "runbook"
    }
    assert types["glossary"]["lookup_keys"] == ["title", "aliases"]
    assert types["decision"]["assigns_seq"] is True
    assert types["decision"]["export_dir"] == "docs/adr"
    assert "avoid" in types["glossary"]["payload_schema"]["properties"]


async def test_list_filters_by_type(client):
    await make(client, "PSN", "PositageNet")
    await make_typed(client, "runbook", "Rotate key", "…")

    r = await client.get("/api/v1/kb", params={"type": "runbook"})
    body = r.json()
    assert [e["title"] for e in body["entries"]] == ["Rotate key"]
    assert body["total"] == 1


async def test_decision_gets_sequential_seq(client):
    first = await make_typed(client, "decision", "Use Postgres", "…")
    second = await make_typed(client, "decision", "Flat threads", "…")
    assert (first["seq"], second["seq"]) == (1, 2)


# ---- repository scoping --------------------------------------------------


async def two_repos(session):
    from cartograph.query import ingest as q_ingest

    a = await q_ingest.upsert_repository(session, "repo_a", "/repos/a")
    b = await q_ingest.upsert_repository(session, "repo_b", "/repos/b")
    await session.flush()
    return a, b


async def test_same_slug_different_repository_allowed(client, session):
    await two_repos(session)
    await make_typed(client, "runbook", "Rotate key", "A", repository="repo_a")
    await make_typed(client, "runbook", "Rotate key", "B", repository="repo_b")


async def test_repo_scoped_entry_shadows_global_in_lookup(client, session):
    await two_repos(session)
    await make(client, "PSN", "the global expansion")
    await make_typed(client, "glossary", "PSN", "repo_a's own expansion", repository="repo_a")

    scoped = await client.get(
        "/api/v1/kb/lookup", params={"term": "psn", "repo": "repo_a"}
    )
    assert scoped.json()["results"][0]["definition"] == "repo_a's own expansion"

    other = await client.get(
        "/api/v1/kb/lookup", params={"term": "psn", "repo": "repo_b"}
    )
    assert other.json()["results"][0]["definition"] == "the global expansion"


async def test_decision_seq_is_per_repository(client, session):
    await two_repos(session)
    a1 = await make_typed(client, "decision", "A one", "…", repository="repo_a")
    b1 = await make_typed(client, "decision", "B one", "…", repository="repo_b")
    a2 = await make_typed(client, "decision", "A two", "…", repository="repo_a")
    assert (a1["seq"], a2["seq"]) == (1, 2)
    assert b1["seq"] == 1


async def test_unknown_repository_is_422(client):
    r = await client.post(
        "/api/v1/kb",
        json={"title": "X", "body": "Y", "repository": "nope"},
    )
    assert r.status_code == 422
