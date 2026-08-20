"""Anthropic Message Batches mode for the summaries phase.

Initial enrichment of a large repo is tens of thousands of one-shot summary
calls — exactly what the Batch API runs at half price without the process
having to stay alive. Four resumable operations, keyed off `enrich_batches`
rows: submit (build prompts, create provider batches, exit), status (poll),
collect (stream results, verify freshness, write summaries), abandon (give
up on batches that can no longer be collected).

Money-safety invariants:
- an `enrich_batches` row is committed BEFORE each provider call (status
  `submitting`) and acknowledged after it (status `submitted`), so a crash or
  lost response never leaves an invisible paid batch;
- submit and collect serialize on a Postgres advisory lock per repository, so
  concurrent invocations cannot double-submit the same nodes;
- a forced resubmit skips nodes covered by an open batch's id span instead of
  paying for them twice;
- collect verifies each node's current content hash (read fresh from the
  database, never the ORM identity map) before writing, and skips nodes
  already summarized from that hash, so re-collecting is idempotent and never
  clobbers paid-for embeddings.

Only summaries are batched. Docs linking and community labels are a few
hundred sequential calls at most, and communities must run after summaries
anyway (labels are prompted from member summaries).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cartograph.config import get_settings
from cartograph.models import EnrichBatch, Repository
from cartograph.query import enrich as q

from .llm import SUMMARY_MODEL, flatten_text, require_api_key
from .summaries import SUMMARY_MAX_TOKENS, build_prompt, read_source

logger = logging.getLogger(__name__)

# `--batch-status` exit code while any batch is still processing, distinct
# from EXIT_PARTIAL_FAILURE so a shell loop can poll on it
EXIT_BATCH_PENDING = 4

# provider retains results for 29 days; nag before they evaporate
RESULTS_RETENTION_WARN_DAYS = 25

HASH_PREFIX_LEN = 16

# `n<id>-<hash prefix>`; [0-9] not \d (\d matches Unicode digits int() may
# still choke on) and ≤18 digits so the id always fits a signed BIGINT
_CUSTOM_ID_RE = re.compile(r"^n([0-9]{1,18})-(.*)$")

# advisory-lock namespace ("cgrb") | repository id: submit/collect/abandon
# for one repo serialize on it, so concurrent invocations can't double-submit
_LOCK_NAMESPACE = 0x63677262 << 32

# a --wait poll tolerates this many consecutive transient failures before
# giving up (the batches themselves are unharmed; --batch-collect resumes)
WAIT_MAX_CONSECUTIVE_FAILURES = 10

# statuses that block a new submit and appear in --batch-status
OPEN_STATUSES = ("submitting", "submitted", "ended")


class BatchStateError(Exception):
    """A batch operation refused because of existing state (open batches,
    concurrent run) — an invocation problem, not a crash. The CLI prints the
    message and exits 2."""


@dataclass
class BatchItemResult:
    custom_id: str
    kind: str  # succeeded | errored | canceled | expired
    text: str | None = None
    error: str | None = None


class BatchClient(Protocol):
    """Provider seam, mirroring LLMClient — tests inject FakeBatchClient."""

    async def submit(
        self, prompts: list[tuple[str, str]], model: str, max_tokens: int
    ) -> str: ...

    async def status(self, batch_id: str) -> tuple[str, dict]: ...

    def results(self, batch_id: str) -> AsyncIterator[BatchItemResult]: ...

    async def cancel(self, batch_id: str) -> None: ...


class AnthropicBatchClient:
    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    async def submit(
        self, prompts: list[tuple[str, str]], model: str, max_tokens: int
    ) -> str:
        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request

        batch = await self._client.messages.batches.create(
            requests=[
                Request(
                    custom_id=custom_id,
                    params=MessageCreateParamsNonStreaming(
                        model=model,
                        max_tokens=max_tokens,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                )
                for custom_id, prompt in prompts
            ]
        )
        return batch.id

    async def status(self, batch_id: str) -> tuple[str, dict]:
        batch = await self._client.messages.batches.retrieve(batch_id)
        return batch.processing_status, batch.request_counts.model_dump()

    async def results(self, batch_id: str) -> AsyncIterator[BatchItemResult]:
        async for entry in await self._client.messages.batches.results(batch_id):
            kind = entry.result.type
            text = error = None
            if kind == "succeeded":
                text = flatten_text(entry.result.message.content)
            elif kind == "errored":
                error = str(entry.result.error)
            yield BatchItemResult(
                custom_id=entry.custom_id, kind=kind, text=text, error=error
            )

    async def cancel(self, batch_id: str) -> None:
        await self._client.messages.batches.cancel(batch_id)


def build_batch_client() -> AnthropicBatchClient:
    return AnthropicBatchClient(require_api_key("--batch"))


def _custom_id(node) -> str:
    # node.id is not stable across re-ingest (loader deletes+reinserts changed
    # files), so the hash prefix lets collect detect a stale result and skip it
    return f"n{node.id}-{(node.content_hash or '')[:HASH_PREFIX_LEN]}"


def _parse_custom_id(custom_id: str) -> tuple[int, str] | None:
    match = _CUSTOM_ID_RE.match(custom_id)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)


def _request_bytes(custom_id: str, prompt: str) -> int:
    """Size of one request as serialized JSON — measured, not estimated.
    ensure_ascii (the default) escapes non-ASCII to \\uXXXX, an upper bound on
    whatever encoding the HTTP layer actually uses, so a chunk that passes
    this bound cannot exceed the provider's 256MB byte cap."""
    return len(
        json.dumps(
            {
                "custom_id": custom_id,
                "params": {
                    "model": SUMMARY_MODEL,
                    "max_tokens": SUMMARY_MAX_TOKENS,
                    "messages": [{"role": "user", "content": prompt}],
                },
            }
        )
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def _acquire_repo_lock(
    session: AsyncSession, repo_id: int, repo_name: str
) -> None:
    key = _LOCK_NAMESPACE | (repo_id & 0xFFFFFFFF)
    got = await session.scalar(select(func.pg_try_advisory_lock(key)))
    if not got:
        raise BatchStateError(
            f"another batch operation for repository {repo_name!r} is already "
            "running — wait for it to finish"
        )


async def _release_repo_lock(session: AsyncSession, repo_id: int) -> None:
    key = _LOCK_NAMESPACE | (repo_id & 0xFFFFFFFF)
    try:
        await session.scalar(select(func.pg_advisory_unlock(key)))
    except PendingRollbackError:
        # a failed transaction blocks the unlock; everything worth keeping was
        # already committed, so discard it and release
        await session.rollback()
        await session.scalar(select(func.pg_advisory_unlock(key)))


async def submit_summaries(
    session: AsyncSession,
    repo: Repository,
    client: BatchClient,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    settings = get_settings()
    repo_id, root = repo.id, Path(repo.root_path)
    await _acquire_repo_lock(session, repo_id, repo.name)
    try:
        open_rows = await q.enrich_batches_by_status(session, repo_id, OPEN_STATUSES)
        if open_rows and not force:
            ids = ", ".join(row.provider_batch_id or "(submitting)" for row in open_rows)
            raise BatchStateError(
                f"repository {repo.name!r} already has uncollected batches ({ids}) — "
                "run --batch-collect first, --batch-abandon to give up on them, or "
                "pass --force to submit only the nodes they don't cover"
            )
        # under --force, nodes inside an open batch's id span are already paid
        # for — skip them instead of billing twice. `submitting` rows count
        # too: if their provider batch never existed, the sync sweep still
        # picks the nodes up (summary IS NULL), which costs less than risking
        # a duplicate batch.
        covered_spans = [
            (row.node_id_min, row.node_id_max)
            for row in open_rows
            if row.node_id_min is not None and row.node_id_max is not None
        ]

        nodes = await q.summary_candidate_rows(
            session, repo_id, settings.SUMMARY_MIN_LINES, limit
        )
        batches = requests = skipped = already_submitted = 0
        pending: list[tuple[str, str]] = []
        pending_bytes = 0
        pending_id_span: list[int] = []

        async def flush() -> None:
            nonlocal batches, requests, pending, pending_bytes, pending_id_span
            if not pending:
                return
            # intent row first: if the provider call succeeds but its response
            # is lost (or we crash), the `submitting` row is the evidence —
            # --batch-status flags it, --batch-abandon clears it
            row = await q.create_enrich_batch(
                session,
                repo_id,
                "summaries",
                len(pending),
                pending_id_span[0],
                pending_id_span[-1],
            )
            await session.commit()
            batch_id = await client.submit(pending, SUMMARY_MODEL, SUMMARY_MAX_TOKENS)
            row.provider_batch_id = batch_id
            row.status = "submitted"
            await session.commit()
            logger.info("batch %s submitted with %d requests", batch_id, len(pending))
            batches += 1
            requests += len(pending)
            pending = []
            pending_bytes = 0
            pending_id_span = []

        logger.info("batch submit: %d nodes need summaries", len(nodes))
        for node in nodes:
            if any(lo <= node.id <= hi for lo, hi in covered_spans):
                already_submitted += 1
                continue
            if not node.content_hash:
                # a hashless node would get a vacuous freshness check and,
                # once written, could never be re-selected (NULL IS DISTINCT
                # FROM NULL is false) — leave it to the sync path
                skipped += 1
                continue
            source = read_source(root, node)
            if source is None:
                skipped += 1
                continue
            prompt = build_prompt(node, source)
            cost = _request_bytes(_custom_id(node), prompt)
            if pending and (
                len(pending) >= settings.BATCH_MAX_REQUESTS
                or pending_bytes + cost > settings.BATCH_MAX_BYTES
            ):
                await flush()
            pending.append((_custom_id(node), prompt))
            pending_bytes += cost
            pending_id_span.append(node.id)
        await flush()
        return {
            "batches": batches,
            "requests": requests,
            "skipped": skipped,
            "already_submitted": already_submitted,
        }
    finally:
        await _release_repo_lock(session, repo_id)


async def check_status(
    session: AsyncSession, repo: Repository, client: BatchClient
) -> dict:
    """Refresh provider status for every uncollected batch of this repo."""
    rows = await q.enrich_batches_by_status(session, repo.id, OPEN_STATUSES)
    snapshots = []
    pending = orphaned = 0
    for row in rows:
        if row.status == "submitted":
            processing_status, counts = await client.status(row.provider_batch_id)
            row.counts = counts
            if processing_status == "ended":
                row.status = "ended"
                row.ended_at = _now()
            elif processing_status in ("canceling", "canceled"):
                row.status = "canceled"
                row.error = f"provider status {processing_status}"
                logger.warning(
                    "batch %s was canceled at the provider — its %d requests "
                    "count as failed at the next --batch-collect",
                    row.provider_batch_id,
                    row.request_count,
                )
        if row.status == "submitted":
            pending += 1
        elif row.status == "submitting":
            orphaned += 1
            logger.warning(
                "batch row %d has no provider id — a submit crashed before the "
                "provider acknowledged it. Check the Console for an orphan "
                "batch; --batch-abandon clears the row, --force skips its span",
                row.id,
            )
        age = _now() - row.submitted_at
        if age > datetime.timedelta(days=RESULTS_RETENTION_WARN_DAYS):
            logger.warning(
                "batch %s is %d days old — results expire after 29 days, collect now",
                row.provider_batch_id,
                age.days,
            )
        snapshots.append(_snapshot(row))
    await session.commit()
    return {"pending": pending, "orphaned": orphaned, "batches": snapshots}


def _snapshot(row: EnrichBatch) -> dict:
    return {
        "provider_batch_id": row.provider_batch_id,
        "status": row.status,
        "request_count": row.request_count,
        "counts": row.counts,
        "submitted_at": row.submitted_at.isoformat(),
    }


_STAT_KEYS = ("written", "unchanged", "stale", "errored", "expired", "canceled")


async def _write_window(
    session: AsyncSession,
    repo_id: int,
    window: list[tuple[int, str, str]],
    stats: dict,
) -> None:
    """Verify one window of (node_id, hash_prefix, summary) against the
    database and bulk-write the survivors."""
    hashes = await q.node_hashes_for_collect(
        session, repo_id, [node_id for node_id, _, _ in window]
    )
    updates = []
    for node_id, hash_prefix, text in window:
        row = hashes.get(node_id)
        if row is None:
            stats["stale"] += 1  # deleted by a re-ingest since submit
            continue
        content_hash, summary_source_hash = row
        if not content_hash or content_hash[:HASH_PREFIX_LEN] != hash_prefix:
            stats["stale"] += 1  # rewritten since submit; sync sweep re-does it
            continue
        if summary_source_hash == content_hash:
            # already summarized from this exact source (an earlier partial
            # collect, or a sync run in between) — rewriting would only null
            # a paid-for embedding
            stats["unchanged"] += 1
            continue
        updates.append(
            {"id": node_id, "summary": text, "summary_source_hash": content_hash}
        )
    await q.set_summaries(session, updates)
    stats["written"] += len(updates)
    await session.commit()


async def _collect_one(
    session: AsyncSession, repo_id: int, client: BatchClient, row: EnrichBatch
) -> dict:
    window_size = max(1, get_settings().ENRICH_COMMIT_EVERY)
    stats = {key: 0 for key in _STAT_KEYS}
    window: list[tuple[int, str, str]] = []
    async for item in client.results(row.provider_batch_id):
        if item.kind != "succeeded":
            stats[item.kind if item.kind in stats else "errored"] += 1
            if item.error:
                logger.warning("batch item %s errored: %s", item.custom_id, item.error)
            continue
        parsed = _parse_custom_id(item.custom_id)
        if parsed is None or not item.text:
            stats["errored"] += 1
            continue
        window.append((parsed[0], parsed[1], item.text))
        if len(window) >= window_size:
            await _write_window(session, repo_id, window, stats)
            window = []
    await _write_window(session, repo_id, window, stats)
    row.status = "collected"
    row.collected_at = _now()
    row.stats = stats
    await session.commit()
    logger.info("batch %s collected: %s", row.provider_batch_id, stats)
    return stats


async def collect_summaries(
    session: AsyncSession, repo: Repository, client: BatchClient
) -> dict:
    repo_id = repo.id
    await _acquire_repo_lock(session, repo_id, repo.name)
    try:
        await check_status(session, repo, client)
        totals = {key: 0 for key in _STAT_KEYS}
        batches_failed = 0
        ended = [
            (row.id, row.provider_batch_id)
            for row in await q.enrich_batches_by_status(session, repo_id, ("ended",))
        ]
        for row_id, provider_batch_id in ended:
            row = await session.get(EnrichBatch, row_id)
            try:
                stats = await _collect_one(session, repo_id, client, row)
            except Exception as exc:
                # one unreadable batch (expired results, 4xx/5xx) must not
                # block the others — record it and keep going; the row stays
                # `ended` so a later --batch-collect (or --batch-abandon)
                # can deal with it
                logger.exception(
                    "collect failed for batch %s — skipping it, the other "
                    "batches still collect",
                    provider_batch_id,
                )
                # the rollback discards any half-written window and expires
                # the session's objects, so re-fetch the row before marking it
                await session.rollback()
                row = await session.get(EnrichBatch, row_id)
                row.error = f"{type(exc).__name__}: {exc}"[:500]
                await session.commit()
                batches_failed += 1
                continue
            for key, value in stats.items():
                totals[key] += value
        # a provider-side cancellation means those requests will never yield
        # results: surface them as failed work exactly once
        for row in await q.enrich_batches_by_status(session, repo_id, ("canceled",)):
            if row.collected_at is not None:
                continue
            totals["canceled"] += row.request_count
            row.stats = {"canceled": row.request_count}
            row.collected_at = _now()
        await session.commit()
        still_open = await q.enrich_batches_by_status(session, repo_id, OPEN_STATUSES)
        # sync-run semantics: anything written off is "failed" and the
        # summaries predicate re-selects it, so `--phase summaries` (sync)
        # retries for free
        totals["failed"] = totals["errored"] + totals["expired"] + totals["canceled"]
        totals["batches_failed"] = batches_failed
        totals["batches_pending"] = len(still_open)
        return totals
    finally:
        await _release_repo_lock(session, repo_id)


async def abandon_batches(
    session: AsyncSession, repo: Repository, client: BatchClient
) -> dict:
    """Give up on every uncollected batch: best-effort provider cancel for the
    ones still processing, then mark the rows abandoned so the resubmit guard
    clears. The nodes stay unsummarized and the sync sweep picks them up."""
    repo_id = repo.id
    await _acquire_repo_lock(session, repo_id, repo.name)
    try:
        rows = await q.enrich_batches_by_status(session, repo_id, OPEN_STATUSES)
        for row in rows:
            if row.status == "submitted" and row.provider_batch_id:
                try:
                    await client.cancel(row.provider_batch_id)
                except Exception as exc:
                    logger.warning(
                        "provider cancel of %s failed (%s) — abandoning locally anyway",
                        row.provider_batch_id,
                        exc,
                    )
            row.status = "abandoned"
            row.error = row.error or "abandoned by operator"
        await session.commit()
        return {"abandoned": len(rows)}
    finally:
        await _release_repo_lock(session, repo_id)


async def wait_and_collect(
    sessionmaker: async_sessionmaker, repo: Repository, client: BatchClient
) -> dict:
    """Poll until every batch ends, then collect. Opens a fresh session per
    poll — holding one connection across a wait that can legitimately run
    for hours is how idle-timeout middleboxes kill it — and tolerates
    transient provider errors (the batches themselves are unharmed;
    --batch-collect resumes after any failure here)."""
    interval = get_settings().BATCH_POLL_INTERVAL_S
    failures = 0
    while True:
        try:
            async with sessionmaker() as session:
                status = await check_status(session, repo, client)
        except Exception:
            failures += 1
            if failures >= WAIT_MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "giving up after %d consecutive status failures — the "
                    "batches are unharmed, resume with --batch-collect",
                    failures,
                )
                raise
            logger.warning(
                "status poll failed (%d/%d) — retrying in %.0fs",
                failures,
                WAIT_MAX_CONSECUTIVE_FAILURES,
                interval,
                exc_info=True,
            )
            await asyncio.sleep(interval)
            continue
        failures = 0
        if not status["pending"]:
            break
        logger.info(
            "waiting on %d batch(es), next poll in %.0fs", status["pending"], interval
        )
        await asyncio.sleep(interval)
    async with sessionmaker() as session:
        return await collect_summaries(session, repo, client)
