from codegraph.query.search import rrf_merge


async def test_text_search_fuzzy(client, seeded):
    r = await client.get(
        "/api/v1/search", params={"q": "ordr", "repo": "seeded", "mode": "text"}
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results, "fuzzy fragment should match OrderService"
    names = [item["node"]["name"] for item in results]
    assert "OrderService" in names
    assert all(item["source"] == "text" for item in results)
    assert all(item["score"] > 0 for item in results)


async def test_text_search_kind_filter(client, seeded):
    r = await client.get(
        "/api/v1/search",
        params={"q": "ordr", "repo": "seeded", "mode": "text", "kinds": "module"},
    )
    assert r.status_code == 200
    names = [item["node"]["name"] for item in r.json()["results"]]
    assert "OrderService" not in names


async def test_invalid_kinds_rejected(client, seeded):
    r = await client.get(
        "/api/v1/search", params={"q": "x", "repo": "seeded", "kinds": "file,banana"}
    )
    assert r.status_code == 422


async def test_semantic_mode_501(client, seeded):
    r = await client.get(
        "/api/v1/search", params={"q": "orders", "repo": "seeded", "mode": "semantic"}
    )
    assert r.status_code == 501


async def test_hybrid_degrades_to_text(client, seeded):
    r = await client.get(
        "/api/v1/search", params={"q": "ordr", "repo": "seeded"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert "OrderService" in [item["node"]["name"] for item in body["results"]]


async def test_unknown_repo_404(client, seeded):
    r = await client.get("/api/v1/search", params={"q": "x", "repo": "nope"})
    assert r.status_code == 404


def test_rrf_merge_order():
    merged = rrf_merge([[1, 2, 3], [3, 1]])
    assert [node_id for node_id, _ in merged] == [1, 3, 2]
    scores = dict(merged)
    assert scores[1] == (1 / 61 + 1 / 62)
    assert scores[3] == (1 / 63 + 1 / 61)
    assert scores[2] == (1 / 62)


def test_rrf_merge_deterministic_on_ties():
    # identical single-list ranks tie only via distinct ranks; equal scores
    # fall back to ascending id
    merged = rrf_merge([[5], [7]])
    assert [node_id for node_id, _ in merged] == [5, 7]
