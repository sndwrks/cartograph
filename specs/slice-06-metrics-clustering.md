# Slice 06 — Metrics & Leiden clustering job

## Goal

A batch job `python -m cartograph.metrics --repo NAME` computes in/out degree, PageRank, Leiden communities, and aggregated inter-community edges, storing everything on the rows the UI reads. After this, the graph has structure: communities exist, god nodes are rankable, and nothing at request time ever runs graph algorithms.

## Depends on

Slice 05 (a populated graph to compute over).

## Spec references

`initial-spec.md` §4 (batch-computed metrics rationale), §8 (threshold-gated re-clustering).

## Requirements

### 1. Job CLI

`python -m cartograph.metrics --repo NAME [--force-recluster] [--changed-edges N]`

- Loads the repo's symbol graph, computes metrics, optionally re-clusters, writes results, exits 0/1.
- `--changed-edges N` is how callers (slice 14's incremental path) report how many edges the preceding ingest added+deleted; clustering is skipped when `N` is below the threshold (see §4 below). A full run (`--force-recluster` or no `--changed-edges` given) always clusters.

Add `python-igraph` to `pyproject.toml`.

### 2. Graph construction

1. Vertices: the repo's nodes of kinds `module`, `class`, `function`, `method`, `doc`, `config` — **exclude `file` nodes and `contains` edges** from metrics/clustering (containment is structural, not informational; including it makes every file a hub).
2. Edges: `imports`, `calls`, `inherits`, `references` among those vertices, any confidence. Directed.
3. Build one igraph `Graph` in-process; keep a vertex-index ↔ node-id mapping.

### 3. Metrics

1. `degree_in` / `degree_out`: directed degrees from the metrics graph (so `contains` doesn't inflate them). Written to every vertex's node row; nodes excluded from the graph (files) keep 0.
2. `pagerank`: igraph PageRank on the directed graph, default damping. Written to node rows.
3. All updates for a repo happen in one transaction (bulk `UPDATE ... FROM (VALUES ...)` or executemany through the query layer).

### 4. Clustering

1. Algorithm: Leiden (`Graph.community_leiden`) on the **undirected** projection, objective `modularity`. Store `algorithm="leiden"`.
2. Threshold gate: config value `RECLUSTER_EDGE_THRESHOLD` (default 50, settable via env). If `--changed-edges` is provided and below it, skip clustering entirely (metrics still run) and log why — community labels must stay stable across small commits.
3. When clustering runs: delete the repo's existing `communities` and `community_edges` rows, insert new `Community` rows (label/summary left NULL — slice 13 fills them), set `Node.community_id`, and populate `node_count` / `internal_edge_count` per community.
4. **Label carry-over (required):** before deleting old communities, snapshot their labeled members; after inserting new ones, copy `label`/`summary` from any old community whose member overlap with a new community exceeds 60% of the smaller set. This keeps tier-3 labels stable across re-clusters.
5. `community_edges`: for every pair of distinct communities with edges between their members, insert one row per direction present with `weight` = count of underlying edges.
6. Discard trivial communities? No — keep all, but communities with a single node are fine; the UI sizes by node_count.

### 7. Query layer additions

`cartograph/query/metrics.py`: load-graph query (nodes+edges for a repo), bulk metric writeback, community replace + carry-over, community-edge aggregation. The job module contains algorithm code only, no SQL.

## Files

- `backend/src/cartograph/metrics/{__init__.py,__main__.py,job.py}`
- `backend/src/cartograph/query/metrics.py`
- `backend/tests/metrics/test_metrics_job.py`

## Acceptance criteria

1. Ingest `py_sample` (slice 05), run `python -m cartograph.metrics --repo py_sample`. Assert: every non-file symbol node has `pagerank > 0`; degrees match a hand-counted fixture symbol (pick one with known in/out edges, `contains` excluded); at least one community exists; every symbol node has a `community_id`; `communities.node_count` sums to the symbol-node count; `community_edges.weight` values match hand-counted cross-community edges.
2. Re-run the job unchanged → identical community memberships (same partition; ids may differ but member sets match) and pagerank stable within float tolerance.
3. Set a label on a community, re-run with `--force-recluster` → the label survives via carry-over (fixture is small enough that partitions repeat).
4. Run with `--changed-edges 3` (below threshold) after a label is set → metrics update, communities untouched (same ids).
5. Job runs in compose: `docker compose run --rm api uv run python -m cartograph.metrics --repo py_sample` exits 0.

## Out of scope

- Community labels/summaries content (slice 13 writes them; this slice only preserves them).
- Any HTTP exposure of metrics (slice 07).
- Scheduling/automation (slice 14 chains ingest → metrics in the hook).
