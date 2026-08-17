"""Batch splitting, partial-failure accounting, and per-batch checkpointing.

The embeddings phase used to hold every UPDATE until one commit after the loop,
so an interrupted run persisted nothing. It also swallowed batch failures into a
counter that nothing downstream read.
"""

import pytest
from sqlalchemy import select

from codegraph.config import get_settings
from codegraph.enrich import embeddings
from codegraph.enrich.runner import failed_phases, run_phases
from codegraph.enrich.voyage import batch_spans, estimate_tokens
from codegraph.models import Node
from fakes import FakeEmbedder


def test_batch_spans_splits_on_item_count():
    assert list(batch_spans(["a"] * 5, max_items=2, max_tokens=0)) == [
        (0, 2),
        (2, 4),
        (4, 5),
    ]


def test_batch_spans_splits_on_token_budget():
    # ~26 estimated tokens each, so a 60-token budget fits two per request
    texts = ["x" * 100] * 5
    assert estimate_tokens(texts[0]) == 26
    assert list(batch_spans(texts, max_items=100, max_tokens=60)) == [
        (0, 2),
        (2, 4),
        (4, 5),
    ]


def test_batch_spans_never_drops_a_text_over_the_budget():
    # Voyage truncates oversized inputs server-side; dropping one here would
    # leave the node permanently unembedded and permanently re-queued
    spans = list(batch_spans(["a", "b" * 10_000, "c"], max_items=10, max_tokens=50))
    assert spans == [(0, 1), (1, 2), (2, 3)]


def test_batch_spans_handles_empty_input():
    assert list(batch_spans([], max_items=8, max_tokens=100)) == []


def test_failed_phases_reports_only_phases_that_wrote_work_off():
    results = {
        "embeddings": {"embedded": 3, "failed": 2},
        "kb": {"embedded": 1, "failed": 0},
        "summaries": {"summarized": 4, "failed": 0, "skipped": 1},
    }
    assert failed_phases(results) == [("embeddings", 2)]


@pytest.fixture
def one_node_per_request(monkeypatch):
    """One node per Voyage request, so failures land on known nodes."""
    settings = get_settings()
    monkeypatch.setattr(settings, "EMBED_BATCH_SIZE", 1)
    monkeypatch.setattr(settings, "EMBED_MAX_TOKENS_PER_REQUEST", 0)


async def summarized_nodes(session, repo):
    # set_embeddings issues bulk UPDATEs, so identity-mapped Nodes hold stale
    # attributes until the select is told to overwrite them
    stmt = (
        select(Node)
        .where(Node.repository_id == repo.id, Node.summary.is_not(None))
        .execution_options(populate_existing=True)
    )
    return list((await session.scalars(stmt)).all())


async def test_failed_batch_keeps_the_other_batches(
    session, repo, fake_llm, one_node_per_request
):
    await run_phases(session, repo, ("summaries",), llm=fake_llm)

    embedder = FakeEmbedder(fail_calls={0})
    stats = await embeddings.run(session, repo, embedder)

    assert stats["failed"] == 1
    assert stats["embedded"] > 0

    nodes = await summarized_nodes(session, repo)
    unembedded = [node for node in nodes if node.embedding is None]
    assert len(unembedded) == 1
    assert stats["embedded"] == len(nodes) - 1


async def test_rerun_retries_only_the_node_that_failed(
    session, repo, fake_llm, one_node_per_request
):
    await run_phases(session, repo, ("summaries",), llm=fake_llm)
    await embeddings.run(session, repo, FakeEmbedder(fail_calls={0}))

    retry = FakeEmbedder()
    stats = await embeddings.run(session, repo, retry)

    # the embedding IS NULL filter makes the phase resume rather than restart
    assert stats == {"embedded": 1, "failed": 0}
    assert len(retry.calls) == 1
    assert all(node.embedding is not None for node in await summarized_nodes(session, repo))


async def test_commits_after_every_batch(
    session, repo, fake_llm, one_node_per_request, monkeypatch
):
    await run_phases(session, repo, ("summaries",), llm=fake_llm)

    commits = 0
    original = session.commit

    async def counting_commit():
        nonlocal commits
        commits += 1
        await original()

    monkeypatch.setattr(session, "commit", counting_commit)
    stats = await embeddings.run(session, repo, FakeEmbedder())

    # one per successful batch, so an interrupt loses at most one batch
    assert stats["embedded"] > 1
    assert commits >= stats["embedded"]
