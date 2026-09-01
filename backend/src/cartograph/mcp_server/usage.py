"""Per-call usage recording for the MCP server.

`UsageMiddleware` sits in the SDK's server-middleware chain and writes one
`tool_calls` row per `tools/call`. Two properties are non-negotiable:

1. It can never fail or visibly slow a tool call. The middleware only
   *enqueues* — a `put_nowait` onto a bounded in-process queue — and a single
   worker task does the parsing and the database writes. A full queue drops
   the row with a throttled warning; a missing table (the mcp service came up
   before the api service migrated) logs the same way and the agent still
   gets its result. Nothing on the request path awaits the database.
2. It measures what the agent actually received. The SDK serializes the
   handler's dict *inside* the middleware chain, so `call_next` returns the
   wire dict: `{"content": [{"type": "text", "text": <pretty JSON>}],
   "isError": ...}`. `response_bytes` is the UTF-8 length of that text —
   including the `indent=2` whitespace, which is a real cost.

Why a queue rather than awaiting inline: an inline await charges the agent
for the recording round trip, holds a second pool connection per in-flight
call, and cannot be bounded safely — cancelling a SQLAlchemy session mid
statement leaves the connection in an undefined state. One serial worker
holds at most one connection, and `json.loads` of a large result runs in a
thread so it never stalls the event loop under the tool calls.

The worker is per process and rows still queued at shutdown are lost; that
is the accepted trade for never being on the request path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from cartograph.config import Settings, get_settings
from cartograph.mcp_server import baseline
from cartograph.models import ToolCall
from cartograph.query.ingest import get_repository_by_name

try:  # the SDK's error type; absent only in a broken install
    from mcp.shared.exceptions import MCPError
except ImportError:  # pragma: no cover
    class MCPError(Exception):  # type: ignore[no-redef]
        pass

logger = logging.getLogger(__name__)

AGENT_HEADER = "x-cartograph-agent"
SESSION_HEADER = "x-cartograph-session"
ERROR_MAX_CHARS = 2000
# a raised exception's text can carry SQL and bound parameters; only its
# first line, shortened, is persisted — the full text goes to the server log
EXCEPTION_MAX_CHARS = 200
# agent_name and client_session land in btree-indexed columns (~2.7KB row
# limit) and are client-controlled
IDENT_MAX_CHARS = 200
# the stored `arguments` document as a whole, on top of the per-value cap:
# a params-validation failure is recorded too, and never reached a tool
ARG_MAX_KEYS = 64
ARG_MAX_TOTAL_BYTES = 16 * 1024
PRUNE_INTERVAL_S = 3600.0


@dataclass
class ToolCallDraft:
    """Everything a row needs except what only the DB can supply
    (repository_id, baseline). Built by the pure `build_draft`."""

    tool: str
    arguments: dict
    request_bytes: int
    repo_arg: str | None
    agent_name: str | None
    client_session: str | None
    started_at: datetime
    duration_ms: int
    ok: bool
    error_kind: str | None
    error: str | None
    response_bytes: int
    result: dict | None = None          # parsed tool dict, when parseable
    result_meta: dict | None = None
    refs: baseline.BaselineRefs | None = field(default=None, repr=False)
    exception_text: str | None = field(default=None, repr=False)  # for the log only


@dataclass
class _Job:
    """What the request path hands to the worker: raw inputs, no parsing."""

    tool: str
    arguments: Mapping[str, Any] | None
    headers: dict[str, str] | None
    wire: Mapping[str, Any] | None
    exc: BaseException | None
    started_at: datetime
    duration_ms: int


def _ident(value: Any) -> str | None:
    return value[:IDENT_MAX_CHARS] if isinstance(value, str) and value else None


def _cap_arguments(arguments: Mapping[str, Any], max_chars: int) -> dict:
    """Long strings (message bodies, KB bodies) and big payloads are what
    bloat rows; everything else is kept verbatim — unless the document as a
    whole is oversized, in which case only its shape is kept."""
    if len(arguments) > ARG_MAX_KEYS:
        return {"_truncated": True, "keys": len(arguments)}
    capped: dict[str, Any] = {}
    truncated: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > max_chars:
            capped[key] = value[:max_chars] + "…"
            truncated.append(key)
        elif not isinstance(value, (str, int, float, bool, type(None))):
            encoded = json.dumps(value, default=str)
            if len(encoded) > 4 * max_chars:
                capped[key] = {"_truncated": True, "bytes": len(encoded.encode())}
                truncated.append(key)
            else:
                capped[key] = value
        else:
            capped[key] = value
    if truncated:
        capped["_truncated"] = truncated
    if len(json.dumps(capped, default=str).encode()) > ARG_MAX_TOTAL_BYTES:
        return {"_truncated": True, "keys": len(arguments)}
    return capped


def _wire_text(wire: Mapping[str, Any]) -> str:
    """Concatenated text content of a CallToolResult wire dict."""
    parts = []
    for block in wire.get("content") or []:
        if isinstance(block, Mapping) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def build_draft(
    tool: str,
    arguments: Mapping[str, Any] | None,
    headers: Mapping[str, str] | None,
    wire: Mapping[str, Any] | None,
    exc: BaseException | None,
    started_at: datetime,
    duration_ms: int,
    settings: Settings,
) -> ToolCallDraft:
    """Pure: classify the outcome and size the exchange.

    Three error tiers, because they reach the middleware differently:
    `protocol` (invalid params / unknown tool — raised out of `call_next`),
    `exception` (the tool raised — `isError` on the wire), and `tool` (the
    tool returned its `{"error": ...}` contract — success on the wire)."""
    arguments = dict(arguments or {})
    request_bytes = len(json.dumps(arguments, default=str).encode())
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    draft = ToolCallDraft(
        tool=tool,
        arguments=_cap_arguments(arguments, settings.USAGE_ARG_MAX_CHARS),
        request_bytes=request_bytes,
        repo_arg=_ident(arguments.get("repo")),
        agent_name=_ident(arguments.get("agent_name")) or _ident(headers.get(AGENT_HEADER)),
        client_session=_ident(headers.get(SESSION_HEADER)),
        started_at=started_at,
        duration_ms=duration_ms,
        ok=True,
        error_kind=None,
        error=None,
        response_bytes=0,
    )
    if exc is not None:
        draft.ok = False
        draft.error_kind = "protocol"
        draft.error = str(exc)[:ERROR_MAX_CHARS]
        return draft
    text = _wire_text(wire or {})
    draft.response_bytes = len(text.encode())
    if wire and wire.get("isError") is True:
        draft.ok = False
        draft.error_kind = "exception"
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        draft.error = first_line[:EXCEPTION_MAX_CHARS]
        draft.exception_text = text[:ERROR_MAX_CHARS]
        return draft
    if draft.response_bytes > settings.USAGE_PARSE_MAX_BYTES:
        return draft
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        return draft
    draft.result = parsed
    draft.result_meta = baseline.result_meta(tool, parsed)
    if "error" in parsed:
        draft.ok = False
        draft.error_kind = "tool"
        draft.error = str(parsed["error"])[:ERROR_MAX_CHARS]
    draft.refs = baseline.extract_refs(tool, parsed)
    return draft


class UsageMiddleware:
    """`ServerMiddleware`: record every tools/call, never get in its way."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        settings: Settings | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings or get_settings()
        self._queue: asyncio.Queue[_Job] | None = None
        self._worker: asyncio.Task | None = None
        self._last_warning = 0.0
        self._last_prune = 0.0
        self.dropped = 0  # rows lost to a full queue, for tests and logs

    # --- request path -------------------------------------------------------

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            result = await call_next(ctx)
        except (MCPError, ValidationError) as exc:
            self._enqueue(ctx, started_at, t0, wire=None, exc=exc)
            raise
        self._enqueue(ctx, started_at, t0, wire=result, exc=None)
        return result

    def _enqueue(self, ctx, started_at, t0, *, wire, exc) -> None:
        if not self._settings.USAGE_RECORDING:
            return
        try:
            params = ctx.params or {}
            tool = params.get("name")
            if not isinstance(tool, str):
                return
            request = getattr(ctx, "request", None)
            headers = getattr(request, "headers", None)
            job = _Job(
                tool=tool,
                arguments=params.get("arguments"),
                headers=dict(headers) if headers is not None else None,
                wire=wire if isinstance(wire, Mapping) else None,
                exc=exc,
                started_at=started_at,
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )
            self._ensure_worker().put_nowait(job)
        except asyncio.QueueFull:
            self.dropped += 1
            self._warn_throttled(RuntimeError(f"usage queue full, {self.dropped} rows dropped"))
        except Exception as rec_exc:  # noqa: BLE001 — recording must never propagate
            self._warn_throttled(rec_exc)

    def _ensure_worker(self) -> asyncio.Queue[_Job]:
        # created lazily: the middleware is built before any event loop runs,
        # and a worker that died (it shouldn't — it catches everything) is
        # replaced rather than leaving a queue nobody drains
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._settings.USAGE_QUEUE_MAX)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(
                self._run(), name="cartograph-usage-recorder"
            )
        return self._queue

    def _warn_throttled(self, exc: BaseException) -> None:
        # a missing table would otherwise log once per call
        now = time.monotonic()
        if now - self._last_warning > 60:
            self._last_warning = now
            logger.warning("usage recording failed (suppressing repeats for 60s): %r", exc)
        else:
            logger.debug("usage recording failed: %r", exc)

    # --- worker ---------------------------------------------------------------

    async def drain(self) -> None:
        """Wait until every queued row has been processed (tests, shutdown)."""
        if self._queue is not None:
            await self._queue.join()

    async def aclose(self) -> None:
        await self.drain()
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._worker = None

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._warn_throttled(exc)
            finally:
                self._queue.task_done()

    async def _process(self, job: _Job) -> None:
        # json.loads of a multi-MB result is CPU the event loop shouldn't pay
        draft = await asyncio.to_thread(
            build_draft,
            job.tool,
            job.arguments,
            job.headers,
            job.wire,
            job.exc,
            job.started_at,
            job.duration_ms,
            self._settings,
        )
        if draft.exception_text:
            logger.warning("tool %s raised: %s", draft.tool, draft.exception_text)
        async with self._sessionmaker() as session:
            await self._persist(session, draft)
        await self._maybe_prune()

    async def _persist(self, session, draft: ToolCallDraft) -> None:
        repository_id = None
        if draft.repo_arg:
            repo = await get_repository_by_name(session, draft.repo_arg)
            repository_id = repo.id if repo is not None else None

        baseline_bytes = baseline_files = None
        meta = dict(draft.result_meta or {})
        if draft.refs is not None:
            if repository_id is None:
                repository_id, candidates = await baseline.resolve_repository(
                    session, draft.refs
                )
                if repository_id is None and not draft.refs.empty:
                    # the same relative path exists in several repositories:
                    # summing across them would inflate the saving, so record
                    # no baseline and say why
                    meta["baseline_skipped"] = "ambiguous_repository"
                    meta["n_repositories"] = candidates
            if repository_id is not None or draft.refs.empty:
                baseline_bytes, baseline_files, missing = await baseline.baseline_bytes(
                    session,
                    draft.refs,
                    repository_id,
                    self._settings.USAGE_BASELINE_FILE_CAP_BYTES,
                )
                if missing:
                    meta["baseline_missing_files"] = missing

        session.add(
            ToolCall(
                tool=draft.tool,
                repository_id=repository_id,
                repo_arg=draft.repo_arg,
                agent_name=draft.agent_name,
                client_session=draft.client_session,
                arguments=draft.arguments,
                request_bytes=draft.request_bytes,
                started_at=draft.started_at,
                duration_ms=draft.duration_ms,
                ok=draft.ok,
                error_kind=draft.error_kind,
                error=draft.error,
                response_bytes=draft.response_bytes,
                baseline_bytes=baseline_bytes,
                baseline_files=baseline_files,
                result_meta=meta or None,
            )
        )
        await session.commit()

    async def _maybe_prune(self) -> None:
        """Retention: drop rows older than USAGE_RETENTION_DAYS, at most once
        an hour, from the worker so it never touches the request path."""
        days = self._settings.USAGE_RETENTION_DAYS
        if days <= 0:
            return
        now = time.monotonic()
        if now - self._last_prune < PRUNE_INTERVAL_S:
            return
        self._last_prune = now
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._sessionmaker() as session:
            result = await session.execute(delete(ToolCall).where(ToolCall.started_at < cutoff))
            await session.commit()
        if result.rowcount:
            logger.info("usage retention: pruned %d tool_calls rows older than %d days", result.rowcount, days)
