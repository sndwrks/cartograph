"""Degrees, PageRank, and Leiden clustering over a repo's symbol graph."""

from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict

import igraph as ig
from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.config import get_settings
from codegraph.models import Repository
from codegraph.query import metrics as q

logger = logging.getLogger(__name__)

# 60% of the smaller member set must overlap for a label to carry over
CARRY_OVER_OVERLAP = 0.6


async def run_metrics(
    session: AsyncSession,
    repo: Repository,
    force_recluster: bool = False,
    changed_edges: int | None = None,
) -> dict:
    node_ids, edge_pairs = await q.load_graph(session, repo.id)
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    graph = ig.Graph(
        n=len(node_ids),
        edges=[(index[src], index[dst]) for src, dst in edge_pairs],
        directed=True,
    )

    if node_ids:
        degree_in = graph.degree(mode="in")
        degree_out = graph.degree(mode="out")
        pagerank = graph.pagerank()
        await q.write_node_metrics(
            session,
            [
                {
                    "id": node_id,
                    "degree_in": degree_in[i],
                    "degree_out": degree_out[i],
                    "pagerank": pagerank[i],
                }
                for i, node_id in enumerate(node_ids)
            ],
        )

    threshold = get_settings().RECLUSTER_EDGE_THRESHOLD
    should_cluster = (
        force_recluster or changed_edges is None or changed_edges >= threshold
    )
    stats = {
        "vertices": len(node_ids),
        "edges": len(edge_pairs),
        "clustered": bool(should_cluster and node_ids),
        "communities": 0,
    }
    if not should_cluster:
        logger.info(
            "skipping clustering: changed_edges=%s below threshold=%s "
            "(community labels stay stable across small commits)",
            changed_edges,
            threshold,
        )
        await session.commit()
        return stats
    if not node_ids:
        await q.delete_communities(session, repo.id)
        await session.commit()
        return stats

    stats["communities"] = await _recluster(
        session, repo.id, node_ids, edge_pairs, graph
    )
    await session.commit()
    return stats


async def _recluster(
    session: AsyncSession,
    repository_id: int,
    node_ids: list[int],
    edge_pairs: list[tuple[int, int]],
    graph: ig.Graph,
) -> int:
    # seeded RNG: identical input graph -> identical partition across runs
    ig.set_random_number_generator(random.Random(42))
    undirected = graph.as_undirected(mode="collapse")
    membership = undirected.community_leiden(
        objective_function="modularity"
    ).membership

    groups: dict[int, set[int]] = defaultdict(set)
    for i, community_index in enumerate(membership):
        groups[community_index].add(node_ids[i])
    member_sets = [groups[key] for key in sorted(groups)]
    community_of = {
        node_id: group_index
        for group_index, members in enumerate(member_sets)
        for node_id in members
    }

    internal: Counter[int] = Counter()
    cross: Counter[tuple[int, int]] = Counter()
    for src, dst in edge_pairs:
        src_group, dst_group = community_of[src], community_of[dst]
        if src_group == dst_group:
            internal[src_group] += 1
        else:
            cross[(src_group, dst_group)] += 1

    labeled = await q.snapshot_labeled_communities(session, repository_id)
    carried: list[tuple[str | None, str | None]] = []
    for members in member_sets:
        carry: tuple[str | None, str | None] = (None, None)
        for old_members, label, summary in labeled:
            overlap = len(members & old_members)
            if overlap > CARRY_OVER_OVERLAP * min(len(members), len(old_members)):
                carry = (label, summary)
                break
        carried.append(carry)

    await q.delete_communities(session, repository_id)
    community_ids = await q.insert_communities(
        session,
        [
            {
                "repository_id": repository_id,
                "label": label,
                "summary": summary,
                "node_count": len(members),
                "internal_edge_count": internal[group_index],
                "algorithm": "leiden",
            }
            for group_index, (members, (label, summary)) in enumerate(
                zip(member_sets, carried)
            )
        ],
    )
    await q.assign_node_communities(
        session,
        [
            {"id": node_id, "community_id": community_ids[group_index]}
            for node_id, group_index in community_of.items()
        ],
    )
    await q.insert_community_edges(
        session,
        [
            {
                "src_community_id": community_ids[src_group],
                "dst_community_id": community_ids[dst_group],
                "weight": weight,
            }
            for (src_group, dst_group), weight in sorted(cross.items())
        ],
    )
    return len(member_sets)
