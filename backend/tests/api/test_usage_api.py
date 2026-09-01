"""Usage endpoints: aggregates over seeded tool_calls rows."""

import datetime

from cartograph.models import Repository, ToolCall

NOW = datetime.datetime.now(datetime.UTC)


def call(tool, *, repo_id=None, ok=True, response=100, baseline=None, files=None,
         agent=None, age=datetime.timedelta(hours=1), duration=10):
    return ToolCall(
        tool=tool,
        repository_id=repo_id,
        agent_name=agent,
        arguments={},
        request_bytes=10,
        started_at=NOW - age,
        duration_ms=duration,
        ok=ok,
        error_kind=None if ok else "tool",
        error=None if ok else "boom",
        response_bytes=response,
        baseline_bytes=baseline,
        baseline_files=files,
        result_meta=None,
    )


async def seed_calls(session, seeded):
    other = Repository(name="other", root_path="/repos/other")
    session.add(other)
    await session.flush()
    rid = seeded.repo.id
    session.add_all(
        [
            # scoped graph calls with baselines
            call("search_code", repo_id=rid, response=400, baseline=4000, files=3, agent="alpha"),
            call("get_node", repo_id=rid, response=600, baseline=1000, files=1, agent="alpha", duration=30),
            # unscoped call, belongs to every repo's view
            call("get_neighbors", response=1000, baseline=0, files=0, agent="beta"),
            # kb call: no baseline, must not enter the ratio
            call("kb_lookup", repo_id=rid, response=5000, agent="beta"),
            # an error
            call("get_node", repo_id=rid, ok=False, response=50, agent="alpha"),
            # outside the 24h window
            call("search_code", repo_id=rid, response=100, baseline=900, files=1, age=datetime.timedelta(days=3)),
            # another repo entirely
            call("search_code", repo_id=other.id, response=999, baseline=999, files=9),
        ]
    )
    await session.flush()


async def test_summary_totals_and_ratio(client, session, seeded):
    await seed_calls(session, seeded)
    r = await client.get("/api/v1/usage/summary", params={"repo": "seeded", "window": "7d"})
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "7d" and body["bucket"] == "day"
    t = body["totals"]
    assert t["calls"] == 6 and t["errors"] == 1 and t["unscoped_calls"] == 1
    assert t["agents"] == 2
    assert t["response_bytes"] == 400 + 600 + 1000 + 5000 + 50 + 100
    # baseline rows only: search(4000/400), get_node(1000/600), unscoped(0/1000), old search(900/100)
    assert t["baseline_calls"] == 4
    assert t["baseline_bytes"] == 5900
    assert t["baseline_response_bytes"] == 2100
    assert t["baseline_files"] == 5
    cpt = body["chars_per_token"]
    assert t["est_tokens_baseline"] == round(5900 / cpt)
    assert t["est_tokens_saved"] == round((5900 - 2100) / cpt)
    assert abs(t["savings_ratio"] - (5900 - 2100) / 5900) < 1e-9

    by_tool = {x["tool"]: x for x in body["by_tool"]}
    assert set(by_tool) == {"search_code", "get_node", "get_neighbors", "kb_lookup"}
    assert by_tool["get_node"]["calls"] == 2 and by_tool["get_node"]["errors"] == 1
    assert by_tool["get_node"]["p50_duration_ms"] == 20.0
    assert by_tool["kb_lookup"]["baseline_bytes"] == 0

    agents = {a["name"]: a for a in body["agents"]}
    assert agents["alpha"]["calls"] == 3 and agents["beta"]["calls"] == 2
    assert sum(b["calls"] for b in body["buckets"]) == 6
    # buckets pair baseline with the response bytes of the SAME rows
    hour_ago = next(b for b in body["buckets"] if b["calls"] == 5)
    assert hour_ago["response_bytes"] == 400 + 600 + 1000 + 5000 + 50
    assert hour_ago["baseline_bytes"] == 5000
    assert hour_ago["baseline_response_bytes"] == 400 + 600 + 1000
    assert hour_ago["start"].endswith("+00:00") or hour_ago["start"].endswith("Z")


async def test_summary_window_filters(client, session, seeded):
    await seed_calls(session, seeded)
    r = await client.get("/api/v1/usage/summary", params={"repo": "seeded", "window": "24h"})
    body = r.json()
    assert body["bucket"] == "hour"
    assert body["totals"]["calls"] == 5
    assert body["totals"]["baseline_calls"] == 3


async def test_summary_no_baseline_rows_has_null_ratio(client, session, seeded):
    session.add(call("kb_lookup", repo_id=seeded.repo.id, response=10))
    await session.flush()
    body = (await client.get("/api/v1/usage/summary", params={"repo": "seeded"})).json()
    assert body["totals"]["calls"] == 1
    assert body["totals"]["savings_ratio"] is None
    assert body["totals"]["est_tokens_saved"] == 0


async def test_summary_all_repos_when_unscoped(client, session, seeded):
    await seed_calls(session, seeded)
    body = (await client.get("/api/v1/usage/summary", params={"window": "all"})).json()
    assert body["totals"]["calls"] == 7


async def test_summary_unknown_repo_404_and_bad_window_422(client, seeded):
    assert (await client.get("/api/v1/usage/summary", params={"repo": "nope"})).status_code == 404
    assert (
        await client.get("/api/v1/usage/summary", params={"repo": "seeded", "window": "1y"})
    ).status_code == 422


async def test_calls_list_filters_and_keyset(client, session, seeded):
    await seed_calls(session, seeded)
    r = await client.get("/api/v1/usage/calls", params={"repo": "seeded"})
    assert r.status_code == 200
    calls = r.json()["calls"]
    assert len(calls) == 6
    ids = [c["id"] for c in calls]
    assert ids == sorted(ids, reverse=True)
    assert {c["repository"] for c in calls} == {"seeded", None}
    assert calls[0].keys() >= {"tool", "agent_name", "arguments", "result_meta", "baseline_bytes", "error"}

    filtered = (await client.get("/api/v1/usage/calls", params={"repo": "seeded", "tool": "get_node"})).json()["calls"]
    assert [c["tool"] for c in filtered] == ["get_node", "get_node"]

    page = (await client.get("/api/v1/usage/calls", params={"repo": "seeded", "limit": 2})).json()["calls"]
    nxt = (await client.get("/api/v1/usage/calls", params={"repo": "seeded", "limit": 2, "before": page[-1]["id"]})).json()["calls"]
    assert len(page) == 2 and len(nxt) == 2 and nxt[0]["id"] < page[-1]["id"]

    by_agent = (await client.get("/api/v1/usage/calls", params={"repo": "seeded", "agent": "beta"})).json()["calls"]
    assert {c["agent_name"] for c in by_agent} == {"beta"} and len(by_agent) == 2

    recent = (await client.get("/api/v1/usage/calls", params={"repo": "seeded", "window": "24h"})).json()["calls"]
    assert len(recent) == 5  # the 3-day-old search is outside the window

    assert (await client.get("/api/v1/usage/calls", params={"repo": "nope"})).status_code == 404
    assert (await client.get("/api/v1/usage/calls", params={"limit": 500})).status_code == 422
    assert (await client.get("/api/v1/usage/calls", params={"window": "1y"})).status_code == 422
