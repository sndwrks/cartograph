CONFIDENCES = {"resolved", "llm_inferred", "name_match"}


def assert_edges_carry_confidence(payload_edges):
    for edge in payload_edges:
        assert edge["confidence"] in CONFIDENCES, edge


async def test_overview(client, seeded):
    r = await client.get("/api/v1/overview", params={"repo": "seeded"})
    assert r.status_code == 200
    body = r.json()
    assert {c["id"] for c in body["communities"]} == {seeded.c1.id, seeded.c2.id}
    labels = {c["id"]: c["label"] for c in body["communities"]}
    assert labels[seeded.c1.id] == "core"
    assert {
        (e["src_community_id"], e["dst_community_id"], e["weight"])
        for e in body["community_edges"]
    } == {(seeded.c1.id, seeded.c2.id, 2), (seeded.c2.id, seeded.c1.id, 2)}
    assert "nodes" not in body


async def test_overview_unknown_repo(client, seeded):
    r = await client.get("/api/v1/overview", params={"repo": "nope"})
    assert r.status_code == 404


async def test_community_graph_full(client, seeded):
    r = await client.get(f"/api/v1/communities/{seeded.c1.id}/graph")
    assert r.status_code == 200
    body = r.json()
    names = [n["name"] for n in body["nodes"]]
    # pagerank descending, file nodes and contains edges absent
    assert names == ["OrderService", "save", "validate", "render", "Base", "helper"]
    rels = {e["rel"] for e in body["edges"]}
    assert "contains" not in rels
    assert len(body["edges"]) == 4  # save->validate, save->render, os->base, helper->validate
    assert_edges_carry_confidence(body["edges"])
    assert {(s["src_id"], s["dst_community_id"], s["weight"]) for s in body["stub_edges"]} == {
        (seeded.render.id, seeded.c2.id, 1),
        (seeded.validate.id, seeded.c2.id, 1),
    }


async def test_community_graph_truncates_by_pagerank(client, seeded):
    r = await client.get(
        f"/api/v1/communities/{seeded.c2.id}/graph", params={"limit": 3}
    )
    body = r.json()
    assert [n["name"] for n in body["nodes"]] == ["cli", "main", "util"]
    # main's two edges into c1 aggregate into one stub of weight 2
    assert {(s["src_id"], s["dst_community_id"], s["weight"]) for s in body["stub_edges"]} == {
        (seeded.main.id, seeded.c1.id, 2)
    }


async def test_node_detail(client, seeded):
    r = await client.get(f"/api/v1/nodes/{seeded.save.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["node"]["qualified_name"] == "app.services.OrderService.save"
    assert body["edge_counts"]["out"]["calls"] == {"resolved": 1, "name_match": 1}
    assert body["edge_counts"]["in"]["calls"] == {"resolved": 1}
    assert (await client.get("/api/v1/nodes/999999")).status_code == 404


async def test_ego_hops_grow(client, seeded):
    r1 = await client.get(f"/api/v1/nodes/{seeded.save.id}/ego", params={"hops": 1})
    r2 = await client.get(f"/api/v1/nodes/{seeded.save.id}/ego", params={"hops": 2})
    ids1 = {n["id"] for n in r1.json()["nodes"]}
    ids2 = {n["id"] for n in r2.json()["nodes"]}
    assert ids1 == {seeded.save.id, seeded.validate.id, seeded.render.id, seeded.main.id}
    assert ids1 < ids2
    assert {seeded.helper.id, seeded.parse.id} <= ids2
    assert_edges_carry_confidence(r1.json()["edges"])
    assert {e["rel"] for e in r2.json()["edges"]} <= {"calls", "inherits", "imports", "references"}


async def test_ego_min_confidence_filters_name_match(client, seeded):
    r = await client.get(
        f"/api/v1/nodes/{seeded.save.id}/ego",
        params={"hops": 1, "min_confidence": "llm_inferred"},
    )
    ids = {n["id"] for n in r.json()["nodes"]}
    # save->render is name_match only, so render disappears
    assert seeded.render.id not in ids
    assert ids == {seeded.save.id, seeded.validate.id, seeded.main.id}
    assert all(e["confidence"] != "name_match" for e in r.json()["edges"])


async def test_impact_upstream_depths(client, seeded):
    r = await client.get(f"/api/v1/nodes/{seeded.validate.id}/impact")
    assert r.status_code == 200
    body = r.json()
    assert body["root_id"] == seeded.validate.id
    depths = {item["node"]["id"]: item["depth"] for item in body["items"]}
    assert depths == {seeded.save.id: 1, seeded.helper.id: 1, seeded.main.id: 2}
    for item in body["items"]:
        assert item["via"]["confidence"] in CONFIDENCES


async def test_impact_survives_cycle(client, seeded):
    r = await client.get(f"/api/v1/nodes/{seeded.parse.id}/impact")
    assert r.status_code == 200
    items = r.json()["items"]
    depths = {item["node"]["id"]: item["depth"] for item in items}
    assert depths[seeded.log.id] == 1
    assert seeded.parse.id not in depths  # root never re-appears
    assert len(items) < 20  # bounded despite the parse <-> log cycle


async def test_impact_downstream(client, seeded):
    r = await client.get(
        f"/api/v1/nodes/{seeded.save.id}/impact", params={"direction": "downstream"}
    )
    depths = {item["node"]["id"]: item["depth"] for item in r.json()["items"]}
    assert depths[seeded.validate.id] == 1
    assert depths[seeded.render.id] == 1
    assert depths[seeded.parse.id] == 2
    assert depths[seeded.log.id] == 3


async def test_god_nodes_order_and_tiebreak(client, seeded):
    r = await client.get(
        "/api/v1/god-nodes", params={"repo": "seeded", "limit": 20}
    )
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    names = [n["name"] for n in nodes]
    assert names[:3] == ["OrderService", "save", "validate"]
    # equal pagerank (0.2): parse (degree 4) outranks log (degree 2)
    assert names.index("parse") < names.index("log")
    assert all(n["kind"] != "file" for n in nodes)


async def test_god_nodes_filters(client, seeded):
    r = await client.get(
        "/api/v1/god-nodes", params={"repo": "seeded", "kind": "class"}
    )
    assert [n["name"] for n in r.json()["nodes"]] == ["OrderService", "Base"]
    r = await client.get(
        "/api/v1/god-nodes",
        params={"repo": "seeded", "community_id": seeded.c2.id, "limit": 2},
    )
    assert [n["name"] for n in r.json()["nodes"]] == ["cli", "main"]
    assert (
        await client.get("/api/v1/god-nodes", params={"repo": "nope"})
    ).status_code == 404


async def test_validation_errors(client, seeded):
    assert (
        await client.get(
            f"/api/v1/nodes/{seeded.save.id}/ego", params={"hops": 7}
        )
    ).status_code == 422
    assert (
        await client.get(
            f"/api/v1/nodes/{seeded.save.id}/impact", params={"direction": "sideways"}
        )
    ).status_code == 422
