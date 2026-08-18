from sqlalchemy import select

from cartograph.mcp_server import tools
from cartograph.models import Agent, Node, NodeKind
from cartograph.query import kb as q_kb


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

    # LOAD-BEARING: kb_lookup's top level is frozen at {match, results}. This
    # is exact dict equality, so a new top-level key (`degraded`, `types`, an
    # always-present `also_matched`) breaks it. New fields go INSIDE a result.
    none = await tools.kb_lookup(session, "unknown-term")
    assert none == {"match": "none", "results": []}


# ---- typed KB over MCP (slice 16) ----------------------------------------

LONG_BODY = (
    "The board is not a lock. No status column, no resolution, no TTL. "
    * 12
) + "That is the whole design."


async def test_kb_lookup_truncates_a_long_body(session):
    await q_kb.create_entry(
        session, "Board protocol", LONG_BODY, type="specification"
    )
    result = await tools.kb_lookup(session, "board protocol")
    [hit] = result["results"]

    assert hit["truncated"] is True
    assert len(hit["definition"]) <= tools.KB_BODY_CAP + 2
    assert hit["definition"].endswith(" …")
    # cut on a sentence boundary, never mid-word
    assert hit["definition"].removesuffix(" …").endswith(".")
    assert hit["slug"] == "board-protocol"


async def test_kb_lookup_does_not_truncate_a_disciplined_entry(session):
    await q_kb.create_entry(session, "PSN", "PositageNet — never any other expansion")
    [hit] = (await tools.kb_lookup(session, "psn"))["results"]
    assert hit["definition"] == "PositageNet — never any other expansion"
    assert "truncated" not in hit


async def test_kb_get_returns_the_full_body(session):
    await q_kb.create_entry(
        session, "Board protocol", LONG_BODY, type="specification"
    )
    entry = await tools.kb_get(session, slug="board-protocol")
    assert entry["definition"] == LONG_BODY
    assert "truncated" not in entry
    assert entry["updated_at"]


async def test_kb_get_index_lists_slugs_without_bodies(session):
    await q_kb.create_entry(session, "Use Postgres", "…", type="decision")
    await q_kb.create_entry(session, "Flat threads", "…", type="decision")
    await q_kb.create_entry(session, "PSN", "PositageNet")

    index = await tools.kb_get(session, type="decision")
    assert index["type"] == "decision"
    assert {e["slug"] for e in index["index"]} == {"use-postgres", "flat-threads"}
    assert all("definition" not in e for e in index["index"])


async def test_kb_get_unknown_type_lists_the_registry(session):
    result = await tools.kb_get(session, type="adr")
    assert "error" in result
    assert "decision" in result["types"]


async def test_kb_lookup_and_get_exclude_proposals(session):
    await q_kb.create_entry(session, "PSN", "PositageNet", status="proposed")
    assert await tools.kb_lookup(session, "psn") == {"match": "none", "results": []}
    assert "error" in await tools.kb_get(session, slug="psn")


async def test_kb_propose_creates_an_invisible_entry(session):
    result = await tools.kb_propose(
        session, "impl-main.kb-0818a", "glossary", "psn", "PSN", "PositageNet"
    )
    assert result["status"] == "proposed"
    assert result["slug"] == "psn"

    # the acceptance criterion for the whole feature
    assert await tools.kb_lookup(session, "psn") == {"match": "none", "results": []}

    entry = await q_kb.get_entry(session, result["id"])
    assert entry.status == "proposed"
    assert entry.source == "mcp"
    assert entry.created_by == "agent:impl-main.kb-0818a"


async def test_kb_propose_self_registers_the_agent(session):
    await tools.kb_propose(
        session, "impl-main.kb-0818a", "glossary", "psn", "PSN", "PositageNet"
    )
    agent = await session.scalar(
        select(Agent).where(Agent.name == "impl-main.kb-0818a")
    )
    assert agent is not None


async def test_kb_propose_is_idempotent(session):
    first = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "PositageNet"
    )
    second = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "PositageNet again"
    )
    assert second == {"status": "duplicate", "id": first["id"], "slug": "psn"}

    count = await q_kb.count_entries(session, status="proposed")
    assert count == 1


async def test_kb_propose_over_a_published_slug_is_a_revision(session):
    await q_kb.create_entry(session, "PSN", "the incumbent")
    result = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "something shorter"
    )
    assert result["status"] == "proposed"
    assert result["revision_of"] == "psn"
    assert result["published_title"] == "PSN"


async def test_kb_propose_after_rejection_returns_the_reason(session):
    entry = await q_kb.create_entry(
        session, "PSN", "PositageNet", status="proposed"
    )
    await q_kb.set_status(
        session, entry.id, "rejected", reason="that is the PlayStation one"
    )
    await session.commit()

    result = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "PositageNet"
    )
    assert result["status"] == "rejected_before"
    assert result["reason"] == "that is the PlayStation one"
    # and nothing was written
    assert await q_kb.count_entries(session, status="proposed") == 0


async def test_kb_propose_unknown_type_lists_the_registry(session):
    result = await tools.kb_propose(session, "agent-a", "adr", "x", "X", "Y")
    assert "unknown type" in result["error"]
    assert "decision" in result["types"]


async def test_kb_propose_invalid_payload_teaches_the_shape(session):
    result = await tools.kb_propose(
        session,
        "agent-a",
        "decision",
        "flat-threads",
        "Flat threads",
        "Re-parent.",
        payload={"decision_status": "maybe"},
    )
    assert "payload invalid" in result["error"]
    assert "context" in result["fields"]  # derived from the registry
    assert result["detail"][0]["field"] == "decision_status"


async def test_mcp_exposes_no_publish_tool(session):
    """Agents may read and propose. Publishing is not 'not exposed' — it is
    not implemented on this layer, and that absence is the enforcement."""
    from cartograph.mcp_server.server import build_mcp_server

    registered = {tool.name for tool in await build_mcp_server().list_tools()}
    assert registered == {
        "search_code", "get_node", "get_neighbors", "impact_of",
        "kb_lookup", "kb_get", "kb_propose",
        "post_message", "read_board",
    }
    assert not any("publish" in name or "reject" in name for name in registered)


# ---- repo scoping and coverage gaps (review findings 6, 14, 28) ----------


async def two_repos(session):
    from cartograph.query import ingest as q_ingest

    a = await q_ingest.upsert_repository(session, "repo_a", "/repos/a")
    b = await q_ingest.upsert_repository(session, "repo_b", "/repos/b")
    await session.flush()
    return a, b


async def test_kb_lookup_is_deterministic_per_repository(session):
    """Two repos may each define a term; unscoped, the tie-break is arbitrary."""
    a, b = await two_repos(session)
    await q_kb.create_entry(session, "PSN", "PositageNet", repository_id=a.id)
    await q_kb.create_entry(session, "PSN", "Payment Service Node", repository_id=b.id)

    from_a = await tools.kb_lookup(session, "psn", repo="repo_a")
    from_b = await tools.kb_lookup(session, "psn", repo="repo_b")
    assert from_a["results"][0]["definition"] == "PositageNet"
    assert from_b["results"][0]["definition"] == "Payment Service Node"
    assert "also_matched" not in from_a and "also_matched" not in from_b


async def test_kb_lookup_repo_scope_prefers_the_local_entry_over_a_global(session):
    a, _ = await two_repos(session)
    await q_kb.create_entry(session, "PSN", "the global one")
    await q_kb.create_entry(session, "PSN", "repo_a's own", repository_id=a.id)

    scoped = await tools.kb_lookup(session, "psn", repo="repo_a")
    assert scoped["results"][0]["definition"] == "repo_a's own"


async def test_kb_lookup_unknown_repo_errors(session):
    assert "error" in await tools.kb_lookup(session, "psn", repo="nope")


async def test_kb_get_is_repo_scoped(session):
    a, b = await two_repos(session)
    await q_kb.create_entry(
        session, "Rotate key", "A steps", type="runbook", repository_id=a.id
    )
    await q_kb.create_entry(
        session, "Rotate key", "B steps", type="runbook", repository_id=b.id
    )

    entry = await tools.kb_get(session, slug="rotate-key", repo="repo_b")
    assert entry["definition"] == "B steps"
    assert "error" in await tools.kb_get(session, slug="rotate-key", repo="nope")


async def test_kb_get_index_reports_truncation(session, monkeypatch):
    monkeypatch.setattr(tools, "INDEX_CAP", 2)
    for name in ("Alpha", "Bravo", "Charlie"):
        await q_kb.create_entry(session, name, "…", type="runbook")

    index = await tools.kb_get(session, type="runbook")
    assert len(index["index"]) == 2
    assert index["truncated"] is True
    assert index["total"] == 3


async def test_kb_get_index_untruncated_has_no_flag(session):
    await q_kb.create_entry(session, "Alpha", "…", type="runbook")
    index = await tools.kb_get(session, type="runbook")
    assert "truncated" not in index and "total" not in index


async def test_kb_get_with_neither_slug_nor_type_explains_itself(session):
    result = await tools.kb_get(session)
    assert "error" in result and "decision" in result["types"]


async def test_kb_propose_scopes_to_a_repository(session):
    a, _ = await two_repos(session)
    result = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "PositageNet", repo="repo_a"
    )
    assert result["status"] == "proposed"
    entry = await q_kb.get_entry(session, result["id"])
    assert entry.repository_id == a.id


async def test_kb_propose_unknown_repo_errors_and_writes_nothing(session):
    result = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "PositageNet", repo="nope"
    )
    assert "unknown repository" in result["error"]
    assert await q_kb.count_entries(session, status="proposed") == 0


async def test_kb_propose_same_slug_in_two_repos_is_not_a_duplicate(session):
    await two_repos(session)
    first = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "A", repo="repo_a"
    )
    second = await tools.kb_propose(
        session, "agent-a", "glossary", "psn", "PSN", "B", repo="repo_b"
    )
    assert first["status"] == "proposed" and second["status"] == "proposed"
    assert first["id"] != second["id"]
