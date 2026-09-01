"""UsageMiddleware: the pure draft builder, the never-fail wrapper, and the
rows it writes through the real chain."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mcp.client import Client
from mcp.shared.exceptions import MCPError
from sqlalchemy import select

from cartograph.config import Settings
from cartograph.mcp_server.server import build_mcp_server
from cartograph.mcp_server.usage import UsageMiddleware, build_draft
from cartograph.models import Node, NodeKind, ToolCall

SETTINGS = Settings(USAGE_ARG_MAX_CHARS=10)
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def wire(payload: dict, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "isError": is_error,
    }


# --- build_draft -------------------------------------------------------------


def test_response_bytes_is_utf8_wire_text():
    payload = {"results": [{"qualified_name": "café"}], "degraded": False}
    draft = build_draft("search_code", {}, None, wire(payload), None, NOW, 5, SETTINGS)
    assert draft.response_bytes == len(json.dumps(payload, indent=2).encode())
    assert draft.ok and draft.error_kind is None
    assert draft.result_meta == {"n_results": 1, "degraded": False}
    assert draft.refs is not None


def test_arguments_capped_but_request_bytes_measured_first():
    args = {"agent_name": "bot", "body": "x" * 100, "payload": {"k": "v" * 100}, "n": 3}
    draft = build_draft("post_message", args, None, wire({"id": 1}), None, NOW, 1, SETTINGS)
    assert draft.request_bytes == len(json.dumps(args).encode())
    assert draft.arguments["body"] == "x" * 10 + "…"
    assert draft.arguments["payload"] == {"_truncated": True, "bytes": len(json.dumps({"k": "v" * 100}).encode())}
    assert draft.arguments["n"] == 3
    assert draft.arguments["_truncated"] == ["body", "payload"]
    assert draft.agent_name == "bot"


def test_header_agent_only_when_argument_absent():
    headers = {"X-Cartograph-Agent": "hdr", "X-Cartograph-Session": "s1"}
    d = build_draft("get_node", {"qualified_name": "x"}, headers, wire({"node": {}}), None, NOW, 1, SETTINGS)
    assert d.agent_name == "hdr" and d.client_session == "s1"
    d = build_draft("post_message", {"agent_name": "arg"}, headers, wire({}), None, NOW, 1, SETTINGS)
    assert d.agent_name == "arg"


def test_identifiers_and_whole_document_are_capped():
    # agent_name lands in an indexed column: capped even though `arguments`
    # keeps its own (per-value) cap
    d = build_draft("post_message", {"agent_name": "a" * 3000}, None, wire({}), None, NOW, 1, SETTINGS)
    assert len(d.agent_name) == 200
    # too many keys (a params-validation reject never reached a tool but is
    # still recorded) collapses to a shape summary, and request_bytes is
    # still the real size
    many = {f"k{i}": i for i in range(500)}
    d = build_draft("nope", many, None, None, RuntimeError("bad params"), NOW, 1, SETTINGS)
    assert d.arguments == {"_truncated": True, "keys": 500}
    assert d.request_bytes == len(json.dumps(many).encode())


def test_error_tiers():
    tool = build_draft("get_node", {}, None, wire({"error": "no node found"}), None, NOW, 1, SETTINGS)
    assert (tool.ok, tool.error_kind, tool.error) == (False, "tool", "no node found")
    assert tool.refs is None

    sql = "(asyncpg.exceptions.UndefinedTableError) relation does not exist\n[SQL: SELECT secret FROM t WHERE k = $1]\n[parameters: ('hunter2',)]"
    exc = build_draft("get_node", {}, None, {"content": [{"type": "text", "text": sql}], "isError": True}, None, NOW, 1, SETTINGS)
    assert (exc.ok, exc.error_kind) == (False, "exception")
    # only the first line is persisted; the SQL and its parameters are not
    assert exc.error == sql.splitlines()[0]
    assert "hunter2" not in exc.error
    assert exc.exception_text == sql  # kept for the server log only
    assert exc.response_bytes == len(sql.encode())

    proto = build_draft("nope", {}, None, None, RuntimeError("bad params"), NOW, 1, SETTINGS)
    assert (proto.ok, proto.error_kind, proto.error) == (False, "protocol", "bad params")
    assert proto.response_bytes == 0


def test_oversized_result_skips_parse_but_keeps_size():
    big = wire({"results": [{"file_path": "a.py"}] * 10})
    settings = Settings(USAGE_PARSE_MAX_BYTES=10)
    draft = build_draft("search_code", {}, None, big, None, NOW, 1, settings)
    assert draft.response_bytes > 10
    assert draft.result is None and draft.refs is None and draft.result_meta is None


# --- middleware wrapper -------------------------------------------------------


def ctx(method="tools/call", name="get_node", arguments=None, request=None):
    return SimpleNamespace(
        method=method,
        params={"name": name, "arguments": arguments or {}},
        request=request,
        request_id=1,
    )


async def test_non_tool_calls_pass_through():
    async def call_next(c):
        return {"tools": []}

    class Boom:
        def __call__(self):
            raise AssertionError("sessionmaker must not be touched")

    mw = UsageMiddleware(Boom(), Settings())
    assert await mw(ctx(method="tools/list"), call_next) == {"tools": []}
    assert mw._queue is None  # nothing was even enqueued


async def test_recording_failure_never_propagates(caplog):
    class Broken:
        def __call__(self):
            raise RuntimeError("relation tool_calls does not exist")

    async def call_next(c):
        return wire({"node": {}})

    mw = UsageMiddleware(Broken(), Settings())
    with caplog.at_level("WARNING", logger="cartograph.mcp_server.usage"):
        assert await mw(ctx(), call_next) == wire({"node": {}})
        assert await mw(ctx(), call_next) == wire({"node": {}})
        await mw.drain()
    # throttled: one warning for two failures
    assert sum("usage recording failed" in r.message for r in caplog.records if r.levelname == "WARNING") == 1
    await mw.aclose()


async def test_full_queue_drops_rows_instead_of_blocking():
    processed = []

    class Recorder(UsageMiddleware):
        async def _process(self, job):
            processed.append(job.tool)
            await asyncio.sleep(0.05)

    async def call_next(c):
        return wire({"node": {}})

    mw = Recorder(None, Settings(USAGE_QUEUE_MAX=2))
    # the worker takes the first job; two more fit the queue; the rest drop
    for _ in range(6):
        assert await mw(ctx(), call_next) == wire({"node": {}})
    assert mw.dropped >= 2
    await mw.drain()
    assert 1 <= len(processed) <= 4
    await mw.aclose()


async def test_protocol_errors_are_recorded_then_reraised():
    calls = []

    class Recorder(UsageMiddleware):
        async def _process(self, job):
            calls.append((job.wire, job.exc))

    async def call_next(c):
        raise MCPError(-32602, "bad params")

    mw = Recorder(None, Settings())
    with pytest.raises(MCPError):
        await mw(ctx(), call_next)
    await mw.drain()
    assert len(calls) == 1 and calls[0][0] is None and isinstance(calls[0][1], MCPError)
    await mw.aclose()


async def test_kill_switch_skips_recording():
    class Boom:
        def __call__(self):
            raise AssertionError("must not record")

    async def call_next(c):
        return wire({"node": {}})

    mw = UsageMiddleware(Boom(), Settings(USAGE_RECORDING=False))
    assert await mw(ctx(), call_next) == wire({"node": {}})
    assert mw._queue is None


# --- through the DB ---------------------------------------------------------


async def _rows(session):
    return list((await session.scalars(select(ToolCall).order_by(ToolCall.id))).all())


async def test_middleware_records_row_with_repo_fallback(session, seeded, test_sessionmaker):
    # give the seeded file node a size so the baseline has something to sum
    seeded.file_node.size_bytes = 1234
    seeded.file_node.file_path = "app/cli.py"
    seeded.main.file_path = "app/cli.py"
    await session.commit()

    payload = {
        "nodes": [
            {"id": seeded.main.id, "qualified_name": "app.cli.main", "file_path": "app/cli.py"},
            {"id": seeded.save.id, "qualified_name": "app.services.OrderService.save", "file_path": "app/services.py"},
        ],
        "edges": [{}],
    }

    async def call_next(c):
        return wire(payload)

    mw = UsageMiddleware(test_sessionmaker, Settings(USAGE_BASELINE_FILE_CAP_BYTES=1000))
    request = SimpleNamespace(headers={"x-cartograph-session": "ab-test-1"})
    await mw(ctx(name="get_neighbors", arguments={"qualified_name": "main"}, request=request), call_next)
    await mw.drain()

    (row,) = await _rows(session)
    assert row.tool == "get_neighbors"
    assert row.repository_id == seeded.repo.id  # resolved from node ids, no `repo` arg
    assert row.repo_arg is None and row.agent_name is None
    assert row.client_session == "ab-test-1"
    assert row.ok and row.error_kind is None
    assert row.response_bytes == len(json.dumps(payload, indent=2).encode())
    # app/cli.py is a sized file (capped 1234 -> 1000); app/services.py has no file node
    assert row.baseline_bytes == 1000 and row.baseline_files == 1
    assert row.result_meta == {"n_nodes": 2, "n_edges": 1}
    assert row.duration_ms >= 0


async def test_unknown_repo_arg_keeps_repo_arg(session, seeded, test_sessionmaker):
    async def call_next(c):
        return wire({"error": "unknown repository 'nope'"})

    mw = UsageMiddleware(test_sessionmaker, Settings())
    await mw(ctx(name="search_code", arguments={"query": "x", "repo": "nope"}), call_next)
    await mw.drain()
    (row,) = await _rows(session)
    assert row.repository_id is None and row.repo_arg == "nope"
    assert (row.ok, row.error_kind) == (False, "tool")
    assert row.baseline_bytes is None


async def _file(session, repo_id, path, size):
    session.add(
        Node(
            repository_id=repo_id,
            kind=NodeKind.file,
            name=path.rsplit("/", 1)[-1],
            qualified_name=path,
            file_path=path,
            size_bytes=size,
        )
    )
    await session.flush()


async def test_unscoped_search_resolves_repo_by_file_owner(session, seeded, test_sessionmaker):
    """search_code results carry paths but no ids; when exactly one
    repository owns those paths the call is attributed to it."""
    await _file(session, seeded.repo.id, "only/here.py", 700)
    await session.commit()

    async def call_next(c):
        return wire({"degraded": False, "results": [{"qualified_name": "only.here", "file_path": "only/here.py"}]})

    mw = UsageMiddleware(test_sessionmaker, Settings())
    await mw(ctx(name="search_code", arguments={"query": "here"}), call_next)
    await mw.drain()
    (row,) = await _rows(session)
    assert row.repository_id == seeded.repo.id and row.repo_arg is None
    assert (row.baseline_bytes, row.baseline_files) == (700, 1)


async def test_unscoped_search_with_shared_path_records_no_baseline(session, seeded, test_sessionmaker):
    """The same relative path in two repositories must not be summed twice."""
    from cartograph.models import Repository

    other = Repository(name="other", root_path="/repos/other")
    session.add(other)
    await session.flush()
    await _file(session, seeded.repo.id, "README.md", 1000)
    await _file(session, other.id, "README.md", 1000)
    await session.commit()

    async def call_next(c):
        return wire({"degraded": False, "results": [{"qualified_name": "README.md", "file_path": "README.md"}]})

    mw = UsageMiddleware(test_sessionmaker, Settings())
    await mw(ctx(name="search_code", arguments={"query": "readme"}), call_next)
    await mw.drain()
    (row,) = await _rows(session)
    assert row.repository_id is None
    assert row.baseline_bytes is None and row.baseline_files is None
    assert row.result_meta["baseline_skipped"] == "ambiguous_repository"
    assert row.result_meta["n_repositories"] == 2


async def test_unscoped_empty_search_has_zero_baseline(session, seeded, test_sessionmaker):
    async def call_next(c):
        return wire({"degraded": True, "results": []})

    mw = UsageMiddleware(test_sessionmaker, Settings())
    await mw(ctx(name="search_code", arguments={"query": "zzz"}), call_next)
    await mw.drain()
    (row,) = await _rows(session)
    assert row.repository_id is None
    assert (row.baseline_bytes, row.baseline_files) == (0, 0)


async def test_resolve_repository(session, seeded):
    from cartograph.mcp_server.baseline import BaselineRefs, resolve_repository

    by_id = BaselineRefs(frozenset(), frozenset(), frozenset({seeded.main.id}))
    assert await resolve_repository(session, by_id) == (seeded.repo.id, 1)
    missing = BaselineRefs(frozenset({"nope.py"}), frozenset(), frozenset())
    assert await resolve_repository(session, missing) == (None, 0)
    assert await resolve_repository(session, BaselineRefs(frozenset(), frozenset(), frozenset())) == (None, 0)


async def test_in_process_client_records_search(session, seeded, test_sessionmaker):
    """Guards the wire contract: the SDK serializes inside the chain, so the
    middleware sees content[0].text. If that ever changes, this fails."""
    mw = UsageMiddleware(test_sessionmaker, Settings())
    server = build_mcp_server(sessionmaker=test_sessionmaker, usage=mw)
    async with Client(server) as client:
        result = await client.call_tool("search_code", {"query": "OrderService", "repo": "seeded"})
    assert not result.is_error
    await mw.drain()

    (row,) = await _rows(session)
    assert row.tool == "search_code"
    assert row.repository_id == seeded.repo.id and row.repo_arg == "seeded"
    assert row.response_bytes > 0
    assert row.result_meta["n_results"] >= 1
    assert row.baseline_bytes is not None  # graph tool: a baseline, even if 0


async def test_baseline_bytes_sums_distinct_files(session, seeded):
    from cartograph.mcp_server.baseline import BaselineRefs, baseline_bytes

    rid = seeded.repo.id
    session.add_all(
        [
            Node(repository_id=rid, kind=NodeKind.file, name="a.py", qualified_name="pkg/a.py", file_path="pkg/a.py", size_bytes=500),
            Node(repository_id=rid, kind=NodeKind.file, name="b.py", qualified_name="pkg/b.py", file_path="pkg/b.py", size_bytes=90_000),
            Node(repository_id=rid, kind=NodeKind.file, name="old.py", qualified_name="pkg/old.py", file_path="pkg/old.py", size_bytes=None),
            Node(repository_id=rid, kind=NodeKind.function, name="f", qualified_name="pkg.a.f", file_path="pkg/a.py"),
        ]
    )
    await session.flush()
    refs = BaselineRefs(frozenset({"pkg/a.py", "pkg/old.py"}), frozenset({"pkg.a.f", "pkg/b.py"}), frozenset())
    total, files, missing = await baseline_bytes(session, refs, rid, file_cap=80_000)
    assert (total, files, missing) == (500 + 80_000, 3, 1)
    # a qualified name in another repo does not leak in
    assert await baseline_bytes(session, refs, rid + 999, 80_000) == (0, 0, 0)
    # and a non-empty ref set without a repository is refused, never summed
    # across repositories
    with pytest.raises(ValueError):
        await baseline_bytes(session, refs, None, 80_000)
    assert await baseline_bytes(session, BaselineRefs(frozenset(), frozenset(), frozenset()), None, 80_000) == (0, 0, 0)
