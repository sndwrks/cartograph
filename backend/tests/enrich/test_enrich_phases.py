from sqlalchemy import select
from sqlalchemy.orm import aliased

from cartograph.config import get_settings
from cartograph.enrich.runner import ALL_PHASES, run_phases
from cartograph.ingest.loader import ingest_repo
from cartograph.models import Community, Edge, EdgeConfidence, EdgeRel, Node, NodeKind
from cartograph.query import kb as q_kb


async def node_by_qname(session, repo_id, qname, kind=None):
    stmt = select(Node).where(
        Node.repository_id == repo_id, Node.qualified_name == qname
    )
    if kind is not None:
        stmt = stmt.where(Node.kind == kind)
    return await session.scalar(stmt)


async def test_full_enrich(session, repo, fake_llm, fake_embedder):
    await q_kb.create_entry(session, "PSN", "PositageNet")
    results = await run_phases(
        session, repo, ALL_PHASES, llm=fake_llm, embedder=fake_embedder
    )

    # summaries: only above-threshold symbols; hash recorded; below-threshold skipped
    base = await node_by_qname(session, repo.id, "pkg.models.Base")
    assert base.summary == "A test summary."
    assert base.summary_source_hash == base.content_hash
    helper = await node_by_qname(session, repo.id, "pkg.util.helper")
    assert helper.summary is None  # 2-line function, under SUMMARY_MIN_LINES

    # embeddings: 1024-dim for every summarized node
    summarized = (
        await session.scalars(
            select(Node).where(
                Node.repository_id == repo.id, Node.summary.is_not(None)
            )
        )
    ).all()
    assert summarized
    assert all(
        node.embedding is not None and len(node.embedding) == 1024
        for node in summarized
    )

    # communities: every community above COMMUNITY_MIN_SIZE labeled. Singletons
    # are deliberately left unlabeled (query/enrich.py: naming a cluster of one
    # costs an LLM call and tells you nothing).
    communities = (
        await session.scalars(
            select(Community).where(Community.repository_id == repo.id)
        )
    ).all()
    min_size = get_settings().COMMUNITY_MIN_SIZE
    labeled = [c for c in communities if c.node_count >= min_size]
    assert labeled
    assert all(c.label == "Test Cluster" for c in labeled)
    assert all(c.label is None for c in communities if c.node_count < min_size)

    # docs: README doc node + llm_inferred references to mentioned symbols
    readme = await node_by_qname(session, repo.id, "README.md", NodeKind.doc)
    assert readme is not None
    assert readme.summary is not None  # docs run first, then get summarized
    dst = aliased(Node)
    reference_targets = {
        qname
        for (qname,) in (
            await session.execute(
                select(dst.qualified_name)
                .select_from(Edge)
                .join(dst, Edge.dst_id == dst.id)
                .where(
                    Edge.src_id == readme.id,
                    Edge.rel == EdgeRel.references,
                    Edge.confidence == EdgeConfidence.llm_inferred,
                )
            )
        ).all()
    }
    assert "pkg.util.helper" in reference_targets

    # kb: entry embedded
    entry = (await q_kb.lookup(session, "PSN"))["results"][0]
    assert entry.embedding is not None and len(entry.embedding) == 1024

    assert results["docs"]["created"] >= 1
    assert results["summaries"]["summarized"] > 0


async def test_cache_rerun_zero_calls(session, repo, fake_llm, fake_embedder):
    await run_phases(session, repo, ALL_PHASES, llm=fake_llm, embedder=fake_embedder)
    fake_llm.calls.clear()
    fake_embedder.calls.clear()

    rerun = await run_phases(
        session, repo, ALL_PHASES, llm=fake_llm, embedder=fake_embedder
    )
    assert fake_llm.calls == []
    assert fake_embedder.calls == []
    assert rerun["summaries"]["summarized"] == 0
    assert rerun["embeddings"]["embedded"] == 0
    assert rerun["docs"]["unchanged"] > 0


async def test_incremental_touch_one_file(
    session, repo, repo_root, fake_llm, fake_embedder
):
    await run_phases(session, repo, ALL_PHASES, llm=fake_llm, embedder=fake_embedder)
    fake_llm.calls.clear()
    fake_embedder.calls.clear()

    util = repo_root / "pkg" / "util.py"
    util.write_text(
        util.read_text() + "\n\ndef extra(x):\n    y = x + 1\n    return y * 2\n"
    )
    await ingest_repo(session, repo)
    await run_phases(session, repo, ALL_PHASES, llm=fake_llm, embedder=fake_embedder)

    # only util.py's nodes hit the fakes (its rows were replaced by re-ingest)
    assert fake_llm.summary_calls, "changed file should be re-summarized"
    for prompt in fake_llm.summary_calls:
        assert "pkg.util" in prompt
    embedded_texts = [
        text for texts, _ in fake_embedder.calls for text in texts
    ]
    assert embedded_texts
    assert all(text.startswith("pkg.util") for text in embedded_texts)
