from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import select

from cartograph.ingest.loader import ingest_repo
from cartograph.metrics.job import run_metrics
from cartograph.models import (
    Community,
    CommunityEdge,
    Edge,
    EdgeConfidence,
    EdgeRel,
    Node,
    NodeKind,
)
from cartograph.query import ingest as qi

FIXTURE = Path(__file__).parents[1] / "extractors" / "fixtures" / "py_sample"

SYMBOL_COUNT = 22  # 28 nodes ingested minus 6 file nodes
# 16 non-contains edges in the DB, minus the 5 name_match ones: the metrics
# graph runs on distinct evidence-confidence pairs only
METRICS_EDGES = 11


@pytest.fixture
async def repo(session):
    repo = await qi.upsert_repository(session, "py_sample", str(FIXTURE))
    await session.commit()
    await ingest_repo(session, repo)
    return repo


async def get_node(session, repo_id, qname):
    return await session.scalar(
        select(Node).where(
            Node.repository_id == repo_id,
            Node.qualified_name == qname,
            Node.kind != NodeKind.file,
        )
    )


async def symbol_nodes(session, repo_id):
    return list(
        (
            await session.scalars(
                select(Node).where(
                    Node.repository_id == repo_id, Node.kind != NodeKind.file
                )
            )
        ).all()
    )


async def member_sets(session, repo_id) -> set[frozenset[int]]:
    nodes = await symbol_nodes(session, repo_id)
    groups: dict[int, set[int]] = {}
    for node in nodes:
        groups.setdefault(node.community_id, set()).add(node.id)
    return {frozenset(members) for members in groups.values()}


async def test_metrics_and_clustering(session, repo):
    stats = await run_metrics(session, repo)
    assert stats["vertices"] == SYMBOL_COUNT
    assert stats["edges"] == METRICS_EDGES
    assert stats["clustered"] is True
    assert stats["communities"] >= 1

    symbols = await symbol_nodes(session, repo.id)
    assert len(symbols) == SYMBOL_COUNT
    for node in symbols:
        assert node.pagerank > 0, node.qualified_name
        # isolated vertices (no evidence edges) stay unclustered rather than
        # becoming singleton communities
        if node.degree_in + node.degree_out > 0:
            assert node.community_id is not None, node.qualified_name
        else:
            assert node.community_id is None, node.qualified_name

    # file nodes are excluded from the metrics graph and keep defaults
    files = (
        await session.scalars(
            select(Node).where(
                Node.repository_id == repo.id, Node.kind == NodeKind.file
            )
        )
    ).all()
    for node in files:
        assert (node.degree_in, node.degree_out, node.pagerank) == (0, 0, 0.0)
        assert node.community_id is None

    # hand-counted, contains excluded: helper is called by cli.main and
    # cached_helper and referenced by cli's module-level `entry = u.helper`
    helper = await get_node(session, repo.id, "pkg.util.helper")
    assert (helper.degree_in, helper.degree_out) == (3, 0)
    # save's name_match edges (n.validate, render x2 out; cli.main's svc.save
    # in) no longer count — only the resolved Node() and self.check() calls do
    save = await get_node(session, repo.id, "pkg.services.OrderService.save")
    assert (save.degree_in, save.degree_out) == (0, 2)

    communities = (
        await session.scalars(
            select(Community).where(Community.repository_id == repo.id)
        )
    ).all()
    clustered = [n for n in symbols if n.community_id is not None]
    assert sum(c.node_count for c in communities) == len(clustered)
    assert all(c.node_count >= 2 for c in communities)
    assert all(c.algorithm == "leiden" for c in communities)

    # community_edges must match cross-community counts recomputed from edges
    community_of = {n.id: n.community_id for n in symbols}
    rows = await session.execute(
        # mirror load_graph: evidence-confidence edges, distinct pairs
        select(Edge.src_id, Edge.dst_id)
        .distinct()
        .where(
            Edge.rel != EdgeRel.contains,
            Edge.confidence != EdgeConfidence.name_match,
            Edge.src_id.in_(community_of),
            Edge.dst_id.in_(community_of),
        )
    )
    expected: Counter[tuple[int, int]] = Counter()
    for src, dst in rows.all():
        src_c, dst_c = community_of[src], community_of[dst]
        if src_c != dst_c:
            expected[(src_c, dst_c)] += 1
    stored = {
        (ce.src_community_id, ce.dst_community_id): ce.weight
        for ce in (await session.scalars(select(CommunityEdge))).all()
        if ce.src_community_id in {c.id for c in communities}
    }
    assert stored == dict(expected)

    internal_total = sum(c.internal_edge_count for c in communities)
    assert internal_total + sum(expected.values()) == METRICS_EDGES


async def test_rerun_is_stable(session, repo):
    await run_metrics(session, repo)
    first_members = await member_sets(session, repo.id)
    first_pagerank = {
        n.qualified_name: n.pagerank for n in await symbol_nodes(session, repo.id)
    }

    await run_metrics(session, repo)
    assert await member_sets(session, repo.id) == first_members
    for node in await symbol_nodes(session, repo.id):
        assert node.pagerank == pytest.approx(first_pagerank[node.qualified_name])


async def test_label_carry_over(session, repo):
    await run_metrics(session, repo)
    helper = await get_node(session, repo.id, "pkg.util.helper")
    community = await session.get(Community, helper.community_id)
    community.label = "utilities"
    community.summary = "helper functions"
    await session.commit()

    await run_metrics(session, repo, force_recluster=True)
    helper = await get_node(session, repo.id, "pkg.util.helper")
    community = await session.get(Community, helper.community_id)
    assert community.label == "utilities"
    assert community.summary == "helper functions"


async def test_threshold_skips_clustering(session, repo):
    await run_metrics(session, repo)
    ids_before = {
        c.id
        for c in (
            await session.scalars(
                select(Community).where(Community.repository_id == repo.id)
            )
        ).all()
    }
    helper = await get_node(session, repo.id, "pkg.util.helper")
    community = await session.get(Community, helper.community_id)
    community.label = "utilities"
    await session.commit()

    stats = await run_metrics(session, repo, changed_edges=3)
    assert stats["clustered"] is False
    ids_after = {
        c.id
        for c in (
            await session.scalars(
                select(Community).where(Community.repository_id == repo.id)
            )
        ).all()
    }
    # communities untouched: identical rows, label intact, metrics still ran
    assert ids_after == ids_before
    community = await session.get(Community, helper.community_id)
    assert community.label == "utilities"
    helper = await get_node(session, repo.id, "pkg.util.helper")
    assert helper.pagerank > 0


async def test_changed_edges_at_threshold_clusters(session, repo):
    stats = await run_metrics(session, repo, changed_edges=50)
    assert stats["clustered"] is True
