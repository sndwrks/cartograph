"""Batch API mode for summaries: submit / status / collect / abandon / CLI."""

import pytest
from sqlalchemy import delete, select, update

from cartograph.config import get_settings
from cartograph.enrich import batch, summaries
from cartograph.enrich import __main__ as enrich_main
from cartograph.enrich.batch import BatchItemResult
from cartograph.models import EnrichBatch, Node
from cartograph.query import enrich as q
from fakes import FakeBatchClient, FakeLLM


async def batch_rows(session, repo_id):
    return list(
        (
            await session.scalars(
                select(EnrichBatch)
                .where(EnrichBatch.repository_id == repo_id)
                .order_by(EnrichBatch.id)
            )
        ).all()
    )


async def test_submit_prompts_match_sync_path(session, repo, fake_llm: FakeLLM):
    client = FakeBatchClient()
    result = await batch.submit_summaries(session, repo, client)
    assert result["batches"] == 1
    assert result["requests"] > 0
    assert result["already_submitted"] == 0

    rows = await batch_rows(session, repo.id)
    assert [row.status for row in rows] == ["submitted"]
    assert rows[0].provider_batch_id == "msgbatch_fake_1"
    assert rows[0].request_count == result["requests"]
    assert rows[0].phase == "summaries"
    assert rows[0].node_id_min is not None
    assert rows[0].node_id_min <= rows[0].node_id_max
    assert client.submit_params == [(batch.SUMMARY_MODEL, summaries.SUMMARY_MAX_TOKENS)]

    # the sync path over the same unsummarized nodes must build byte-identical
    # prompts — batch and sync summaries are interchangeable (requirement:
    # batching changes transport, never output)
    await summaries.run(session, repo, fake_llm)
    submitted_prompts = {prompt for _cid, prompt in client.submitted["msgbatch_fake_1"]}
    assert submitted_prompts == set(fake_llm.summary_calls)

    # custom_ids resolve back to live nodes with matching hash prefixes
    for custom_id, _prompt in client.submitted["msgbatch_fake_1"]:
        node_id, prefix = batch._parse_custom_id(custom_id)
        node = await session.get(Node, node_id)
        assert node is not None
        assert (node.content_hash or "")[: batch.HASH_PREFIX_LEN] == prefix


async def test_chunking_by_request_count(session, repo, monkeypatch):
    monkeypatch.setattr(get_settings(), "BATCH_MAX_REQUESTS", 2)
    client = FakeBatchClient()
    result = await batch.submit_summaries(session, repo, client)

    assert result["batches"] >= 2
    all_ids = [cid for prompts in client.submitted.values() for cid, _ in prompts]
    assert len(all_ids) == len(set(all_ids)) == result["requests"]
    rows = await batch_rows(session, repo.id)
    assert len(rows) == result["batches"]
    assert sum(row.request_count for row in rows) == result["requests"]
    # spans are contiguous and disjoint (id-ordered iteration)
    spans = [(row.node_id_min, row.node_id_max) for row in rows]
    assert all(lo <= hi for lo, hi in spans)
    for (_, prev_hi), (next_lo, _) in zip(spans, spans[1:]):
        assert prev_hi < next_lo


async def test_chunking_by_byte_bound(session, repo, monkeypatch):
    # every request exceeds one byte, so each flush carries exactly one
    monkeypatch.setattr(get_settings(), "BATCH_MAX_BYTES", 1)
    client = FakeBatchClient()
    result = await batch.submit_summaries(session, repo, client)
    assert result["batches"] == result["requests"] > 1


async def test_collect_happy_path(session, repo):
    client = FakeBatchClient()
    await batch.submit_summaries(session, repo, client)
    totals = await batch.collect_summaries(session, repo, client)

    assert totals["failed"] == 0
    assert totals["written"] > 0
    assert totals["unchanged"] == 0
    assert totals["batches_failed"] == 0
    assert totals["batches_pending"] == 0

    rows = await batch_rows(session, repo.id)
    assert all(row.status == "collected" for row in rows)
    assert all(row.collected_at is not None for row in rows)
    assert rows[0].stats["written"] == totals["written"]

    written = (
        await session.scalars(
            select(Node).where(
                Node.repository_id == repo.id, Node.summary == "A batch summary."
            )
        )
    ).all()
    assert len(written) == totals["written"]
    for node in written:
        assert node.summary_source_hash == node.content_hash
        assert node.embedding is None  # queued for the embeddings phase

    # bookkeeping proof: nothing left for the sync path
    remaining = await q.nodes_needing_summary(
        session, repo.id, get_settings().SUMMARY_MIN_LINES
    )
    assert remaining == []


async def test_collect_skips_stale_and_deleted_nodes(session, repo):
    client = FakeBatchClient()
    await batch.submit_summaries(session, repo, client)

    custom_ids = [cid for cid, _ in client.submitted["msgbatch_fake_1"]]
    changed_id, _ = batch._parse_custom_id(custom_ids[0])
    deleted_id, _ = batch._parse_custom_id(custom_ids[1])
    # core UPDATE, not ORM attribute mutation: the freshness check must read
    # the database, and a cached identity-map instance would still hold the
    # submit-time hash — this is what distinguishes the two implementations
    await session.execute(
        update(Node)
        .where(Node.id == changed_id)
        .values(content_hash="rewritten-since-submit")
    )
    await session.execute(delete(Node).where(Node.id == deleted_id))
    await session.flush()

    totals = await batch.collect_summaries(session, repo, client)
    assert totals["stale"] == 2
    assert totals["written"] == len(custom_ids) - 2
    changed_summary = await session.scalar(
        select(Node.summary).where(Node.id == changed_id)
    )
    assert changed_summary is None  # never written with a stale result


async def test_collect_counts_failures_and_leaves_them_selectable(session, repo):
    client = FakeBatchClient()
    await batch.submit_summaries(session, repo, client)

    custom_ids = [cid for cid, _ in client.submitted["msgbatch_fake_1"]]
    client.outcomes[custom_ids[0]] = BatchItemResult(
        custom_id=custom_ids[0], kind="errored", error="overloaded"
    )
    client.outcomes[custom_ids[1]] = BatchItemResult(
        custom_id=custom_ids[1], kind="expired"
    )

    totals = await batch.collect_summaries(session, repo, client)
    assert totals["errored"] == 1
    assert totals["expired"] == 1
    assert totals["failed"] == 2

    # the write-offs stay selectable, so a sync run retries them for free
    remaining = await q.nodes_needing_summary(
        session, repo.id, get_settings().SUMMARY_MIN_LINES
    )
    remaining_ids = {node.id for node in remaining}
    assert {batch._parse_custom_id(cid)[0] for cid in custom_ids[:2]} == remaining_ids


async def test_collect_isolates_a_failing_batch(session, repo, monkeypatch):
    monkeypatch.setattr(get_settings(), "BATCH_MAX_REQUESTS", 2)
    # collect's failure path rolls the session back, which expires `repo`
    repo_id = repo.id
    client = FakeBatchClient(fail_results={"msgbatch_fake_1"})
    submitted = await batch.submit_summaries(session, repo, client)
    assert submitted["batches"] >= 2

    totals = await batch.collect_summaries(session, repo, client)
    assert totals["batches_failed"] == 1
    assert totals["written"] == submitted["requests"] - 2  # the other batches landed

    rows = await batch_rows(session, repo_id)
    failing = [row for row in rows if row.provider_batch_id == "msgbatch_fake_1"]
    assert failing[0].status == "ended"  # retryable, not silently dropped
    assert "simulated unreadable results" in failing[0].error
    assert all(
        row.status == "collected" for row in rows if row is not failing[0]
    )

    # once the provider recovers, a re-collect finishes the job
    client.fail_results.clear()
    await session.refresh(repo)  # collect's rollback expired it
    retry = await batch.collect_summaries(session, repo, client)
    assert retry["written"] == 2
    assert retry["batches_failed"] == 0


async def test_recollect_is_idempotent_and_preserves_embeddings(session, repo):
    client = FakeBatchClient()
    await batch.submit_summaries(session, repo, client)
    first = await batch.collect_summaries(session, repo, client)
    assert first["written"] > 0

    # embeddings ran in the meantime; a re-collect must not null them
    embedded_id, _ = batch._parse_custom_id(
        client.submitted["msgbatch_fake_1"][0][0]
    )
    await session.execute(
        update(Node).where(Node.id == embedded_id).values(embedding=[0.5] * 1024)
    )
    rows = await batch_rows(session, repo.id)
    rows[0].status = "ended"  # simulate a crash that lost the collected mark
    rows[0].collected_at = None
    await session.flush()

    second = await batch.collect_summaries(session, repo, client)
    assert second["written"] == 0
    assert second["unchanged"] == first["written"]
    embedding = await session.scalar(
        select(Node.embedding).where(Node.id == embedded_id)
    )
    assert embedding is not None


async def test_canceled_batch_is_reported_once_as_failed(session, repo):
    client = FakeBatchClient(statuses=["canceled"])
    submitted = await batch.submit_summaries(session, repo, client)

    totals = await batch.collect_summaries(session, repo, client)
    assert totals["canceled"] == submitted["requests"]
    assert totals["failed"] == submitted["requests"]

    # not double-counted by a second collect
    again = await batch.collect_summaries(session, repo, client)
    assert again["canceled"] == 0
    assert again["failed"] == 0


async def test_resubmit_guard_and_forced_span_skip(session, repo):
    client = FakeBatchClient()
    first = await batch.submit_summaries(session, repo, client)

    with pytest.raises(batch.BatchStateError):
        await batch.submit_summaries(session, repo, client)

    # --force does not double-bill: nodes inside the open batch's span are
    # skipped, and nothing else needs a summary
    forced = await batch.submit_summaries(session, repo, client, force=True)
    assert forced["batches"] == 0
    assert forced["requests"] == 0
    assert forced["already_submitted"] == first["requests"]


async def test_abandon_clears_the_guard_and_cancels_upstream(session, repo):
    client = FakeBatchClient()
    await batch.submit_summaries(session, repo, client)

    result = await batch.abandon_batches(session, repo, client)
    assert result["abandoned"] == 1
    assert client.canceled == ["msgbatch_fake_1"]
    rows = await batch_rows(session, repo.id)
    assert rows[0].status == "abandoned"

    # abandoned rows neither block nor span-protect: a fresh submit re-covers
    # the nodes
    resubmitted = await batch.submit_summaries(session, repo, client)
    assert resubmitted["requests"] > 0


async def test_status_reports_pending_then_ended(session, repo):
    client = FakeBatchClient(statuses=["in_progress"])
    await batch.submit_summaries(session, repo, client)

    first = await batch.check_status(session, repo, client)
    assert first["pending"] == 1
    assert first["orphaned"] == 0
    assert first["batches"][0]["status"] == "submitted"

    second = await batch.check_status(session, repo, client)
    assert second["pending"] == 0
    assert second["batches"][0]["status"] == "ended"
    # ended rows are terminal for status(): no further provider calls
    third = await batch.check_status(session, repo, client)
    assert client.status_calls == 2
    assert third["pending"] == 0


async def test_status_flags_orphaned_submitting_rows(session, repo):
    client = FakeBatchClient()
    # a submit that crashed between the intent commit and the provider ack
    await q.create_enrich_batch(session, repo.id, "summaries", 5, 1, 5)
    await session.commit()

    status = await batch.check_status(session, repo, client)
    assert status["orphaned"] == 1
    assert status["batches"][0]["provider_batch_id"] is None

    with pytest.raises(batch.BatchStateError):
        await batch.submit_summaries(session, repo, client)


# --- CLI wiring -------------------------------------------------------------


class _SessionCtx:
    """Hands amain the test session without closing it on exit."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def cli(session, monkeypatch):
    client = FakeBatchClient()
    monkeypatch.setattr(
        enrich_main, "get_sessionmaker", lambda: lambda: _SessionCtx(session)
    )
    monkeypatch.setattr(enrich_main, "build_batch_client", lambda: client)

    async def run(*argv: str) -> int:
        return await enrich_main.amain(enrich_main.build_parser().parse_args(argv))

    return client, run


async def test_cli_batch_requires_summaries_phase(cli, repo):
    _client, run = cli
    assert await run("--repo", "py_sample", "--batch") == 2


async def test_cli_unknown_repo(cli):
    _client, run = cli
    assert await run("--repo", "nope", "--batch-status") == 2


async def test_cli_status_exit_codes(cli, repo):
    client, run = cli
    client.statuses = ["in_progress"]
    assert await run("--repo", "py_sample", "--phase", "summaries", "--batch") == 0
    assert await run("--repo", "py_sample", "--batch-status") == batch.EXIT_BATCH_PENDING
    assert await run("--repo", "py_sample", "--batch-status") == 0


async def test_cli_guard_maps_to_exit_2(cli, repo):
    _client, run = cli
    assert await run("--repo", "py_sample", "--phase", "summaries", "--batch") == 0
    assert await run("--repo", "py_sample", "--phase", "summaries", "--batch") == 2


async def test_cli_collect_partial_failure_exits_3(cli, repo, session):
    client, run = cli
    assert await run("--repo", "py_sample", "--phase", "summaries", "--batch") == 0
    cid = client.submitted["msgbatch_fake_1"][0][0]
    client.outcomes[cid] = BatchItemResult(custom_id=cid, kind="expired")
    assert await run("--repo", "py_sample", "--batch-collect") == 3


async def test_cli_batch_wait_submits_polls_and_collects(
    cli, repo, session, monkeypatch
):
    client, run = cli
    client.statuses = ["in_progress"]
    monkeypatch.setattr(get_settings(), "BATCH_POLL_INTERVAL_S", 0.0)
    code = await run(
        "--repo", "py_sample", "--phase", "summaries", "--batch", "--wait"
    )
    assert code == 0
    rows = await batch_rows(session, repo.id)
    assert [row.status for row in rows] == ["collected"]


async def test_cli_abandon(cli, repo, session):
    client, run = cli
    assert await run("--repo", "py_sample", "--phase", "summaries", "--batch") == 0
    assert await run("--repo", "py_sample", "--batch-abandon") == 0
    assert client.canceled == ["msgbatch_fake_1"]


def test_cli_wait_requires_batch():
    with pytest.raises(SystemExit) as excinfo:
        enrich_main.main(["--repo", "x", "--batch-collect", "--wait"])
    assert excinfo.value.code == 2
