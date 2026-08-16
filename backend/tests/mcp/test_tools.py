from codegraph.mcp_server import tools
from codegraph.models import Node, NodeKind
from codegraph.query import kb as q_kb


async def test_search_code_finds_and_degrades(session, seeded):
    result = await tools.search_code(session, "ordr", repo="seeded")
    assert result["degraded"] is True
    names = [r["qualified_name"] for r in result["results"]]
    assert "app.services.OrderService" in names
    assert all("score" in r and "kind" in r for r in result["results"])


async def test_search_code_unknown_repo(session, seeded):
    result = await tools.search_code(session, "x", repo="nope")
    assert "error" in result


async def test_get_node_by_qualified_name(session, seeded):
    result = await tools.get_node(session, "app.services.OrderService.save")
    assert result["node"]["qualified_name"] == "app.services.OrderService.save"
    assert result["edge_counts"]["out"]["calls"] == {"resolved": 1, "name_match": 1}
    out = {(e["qualified_name"], e["rel"], e["confidence"]) for e in result["edges_out"]}
    assert ("app.models.Node.validate", "calls", "resolved") in out
    assert ("app.models.render", "calls", "name_match") in out
    incoming = {(e["qualified_name"], e["confidence"]) for e in result["edges_in"]}
    assert ("app.cli.main", "resolved") in incoming
    for e in [*result["edges_out"], *result["edges_in"]]:
        assert e["confidence"] in ("resolved", "llm_inferred", "name_match")


async def test_get_node_by_unique_bare_name(session, seeded):
    result = await tools.get_node(session, "helper")
    assert result["node"]["qualified_name"] == "app.util.helper"


async def test_get_node_ambiguous_returns_candidates(session, seeded):
    session.add(
        Node(
            repository_id=seeded.repo.id,
            kind=NodeKind.function,
            name="helper",
            qualified_name="app.other.helper",
        )
    )
    await session.flush()
    result = await tools.get_node(session, "helper")
    assert "error" in result
    assert {c["qualified_name"] for c in result["candidates"]} == {
        "app.util.helper",
        "app.other.helper",
    }


async def test_get_node_not_found(session, seeded):
    result = await tools.get_node(session, "does.not.Exist")
    assert "error" in result and "candidates" not in result


async def test_get_neighbors_min_confidence(session, seeded):
    unfiltered = await tools.get_neighbors(
        session, "app.services.OrderService.save", hops=1
    )
    assert {n["qualified_name"] for n in unfiltered["nodes"]} == {
        "app.services.OrderService.save",
        "app.models.Node.validate",
        "app.models.render",
        "app.cli.main",
    }
    filtered = await tools.get_neighbors(
        session, "app.services.OrderService.save", hops=1, min_confidence="llm_inferred"
    )
    names = {n["qualified_name"] for n in filtered["nodes"]}
    assert "app.models.render" not in names  # name_match-only path filtered out
    assert all(e["confidence"] != "name_match" for e in filtered["edges"])


async def test_impact_of_depths(session, seeded):
    result = await tools.impact_of(session, "app.models.Node.validate")
    assert result["root"] == "app.models.Node.validate"
    depths = {item["node"]["qualified_name"]: item["depth"] for item in result["items"]}
    assert depths == {
        "app.services.OrderService.save": 1,
        "app.util.helper": 1,
        "app.cli.main": 2,
    }
    for item in result["items"]:
        assert item["via"]["confidence"] in ("resolved", "llm_inferred", "name_match")


async def test_impact_of_invalid_direction(session, seeded):
    assert "error" in await tools.impact_of(session, "helper", direction="sideways")


async def test_kb_lookup_psn_determinism(session):
    await q_kb.create_entry(
        session, "PSN", "PositageNet — never any other expansion", aliases=["POS-NET"]
    )
    await q_kb.create_entry(
        session, "PlayStation", "Sony console; its playstation network is called psn"
    )

    for query in ("PSN", "psn", "Psn"):
        result = await tools.kb_lookup(session, query)
        assert result["match"] == "exact"
        assert len(result["results"]) == 1
        assert result["results"][0]["definition"].startswith("PositageNet")

    alias = await tools.kb_lookup(session, "pos-net")
    assert alias["match"] == "alias"
    assert alias["results"][0]["term"] == "PSN"

    none = await tools.kb_lookup(session, "unknown-term")
    assert none == {"match": "none", "results": []}
