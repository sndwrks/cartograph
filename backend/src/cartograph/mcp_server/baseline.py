"""The usage baseline: what a tool call saved an agent from reading.

Every graph tool answers a question an agent could have answered by hand with
grep and file reads. The *baseline* for a call is the size of the distinct
source files that hand method would plausibly have opened; the dashboard
compares it with the bytes the tool actually returned. It is a modelled
counterfactual, deliberately conservative and documented, not a measurement:

- `search_code`  -> the files the results live in. Empty results -> 0, a
  call that saved nothing should say so.
- `get_node`     -> the node's own file plus the files of its *incoming*
  edges. Callers need a grep and a read each; outgoing edges are visible in
  the node's own file, so they are not counted.
- `get_neighbors`-> the files of every returned node (including the root:
  the agent has to start somewhere).
- `impact_of`    -> the files of every impacted node, root excluded (the
  agent already knows the root).
- knowledge-base and board tools -> None. They replace asking a human, not
  reading files; a fake 0 would drag the savings ratio down.

Per-file bytes are capped (`USAGE_BASELINE_FILE_CAP_BYTES`) because an agent
reads a window, not the whole file, and the same file across two calls counts
twice — an agent would read it once. Both biases are documented on the
dashboard rather than corrected here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Node, NodeKind

GRAPH_TOOLS = frozenset({"search_code", "get_node", "get_neighbors", "impact_of"})


@dataclass(frozen=True)
class BaselineRefs:
    """What a result points at, before any DB lookup."""

    file_paths: frozenset[str]        # named directly in the result
    qualified_names: frozenset[str]   # need a qname -> file_path lookup
    node_ids: frozenset[int]          # for repository resolution without `repo`

    @property
    def empty(self) -> bool:
        return not (self.file_paths or self.qualified_names)


def _paths(items: Iterable[Mapping]) -> set[str]:
    return {p for it in items if isinstance(p := it.get("file_path"), str)}


def extract_refs(tool: str, result: Mapping) -> BaselineRefs | None:
    """Pure: pull the file/name references a baseline needs out of a tool's
    result dict. None means "no counterfactual" (non-graph tools, errors)."""
    if tool not in GRAPH_TOOLS or "error" in result:
        return None
    paths: set[str] = set()
    qnames: set[str] = set()
    ids: set[int] = set()
    if tool == "search_code":
        paths = _paths(result.get("results") or [])
    elif tool == "get_node":
        node = result.get("node") or {}
        paths = _paths([node])
        if isinstance(node.get("id"), int):
            ids.add(node["id"])
        qnames = {
            q
            for e in result.get("edges_in") or []
            if isinstance(q := e.get("qualified_name"), str)
        }
    elif tool == "get_neighbors":
        nodes = result.get("nodes") or []
        paths = _paths(nodes)
        ids = {n["id"] for n in nodes if isinstance(n.get("id"), int)}
    elif tool == "impact_of":
        root = result.get("root")
        items = [
            it["node"]
            for it in result.get("items") or []
            if isinstance(it.get("node"), Mapping) and it["node"].get("qualified_name") != root
        ]
        paths = _paths(items)
        ids = {n["id"] for n in items if isinstance(n.get("id"), int)}
    return BaselineRefs(frozenset(paths), frozenset(qnames), frozenset(ids))


def result_meta(tool: str, result: Mapping) -> dict:
    """Pure: the per-tool counts worth keeping on the row."""
    if "error" in result:
        meta: dict = {"error": True}
        if "candidates" in result:
            meta["n_candidates"] = len(result["candidates"])
        return meta
    match tool:
        case "search_code":
            return {
                "n_results": len(result.get("results") or []),
                "degraded": bool(result.get("degraded")),
            }
        case "get_node":
            return {
                "n_edges_in": len(result.get("edges_in") or []),
                "n_edges_out": len(result.get("edges_out") or []),
            }
        case "get_neighbors":
            return {
                "n_nodes": len(result.get("nodes") or []),
                "n_edges": len(result.get("edges") or []),
            }
        case "impact_of":
            items = result.get("items") or []
            return {
                "n_items": len(items),
                "max_depth_seen": max((it.get("depth", 0) for it in items), default=0),
            }
        case "kb_lookup":
            return {
                "match": result.get("match"),
                "n_results": len(result.get("results") or []),
            }
        case "kb_get":
            if "index" in result:
                return {"n_index": len(result["index"]), "truncated": bool(result.get("truncated"))}
            return {"slug": result.get("slug")}
        case "kb_propose":
            return {"status": result.get("status")}
        case "post_message":
            return {"thread_id": result.get("thread_id")}
        case "read_board":
            if "messages" in result:
                return {"n_messages": len(result["messages"])}
            return {"n_threads": len(result.get("threads") or [])}
    return {}


async def resolve_repository(
    session: AsyncSession, refs: BaselineRefs
) -> tuple[int | None, int]:
    """(repository_id, n_candidates) for a call that named no `repo`.

    Node ids are exact (get_node, get_neighbors, impact_of carry them).
    search_code results carry only paths, so fall back to "which
    repositories own a file node at these paths" — usable only when that is
    exactly one. Summing a path that exists in several repositories would
    count every copy, so the caller records no baseline in that case."""
    if refs.node_ids:
        rid = await session.scalar(
            select(Node.repository_id).where(Node.id.in_(refs.node_ids)).limit(1)
        )
        if rid is not None:
            return rid, 1
    if refs.file_paths:
        owners = (
            await session.scalars(
                select(Node.repository_id)
                .distinct()
                .where(Node.kind == NodeKind.file, Node.file_path.in_(refs.file_paths))
            )
        ).all()
        if len(owners) == 1:
            return owners[0], 1
        return None, len(owners)
    return None, 0


async def baseline_bytes(
    session: AsyncSession,
    refs: BaselineRefs,
    repository_id: int | None,
    file_cap: int,
) -> tuple[int, int, int]:
    """(bytes, files, files_without_size) for the distinct files behind
    `refs`, within ONE repository. Files ingested before `size_bytes` existed
    contribute 0 and are counted in the third slot so the estimate is visibly
    incomplete. Without a repository only an empty ref set is answerable —
    paths are relative and may exist in several repositories."""
    if refs.empty:
        return 0, 0, 0
    if repository_id is None:
        raise ValueError("baseline_bytes needs a repository_id for non-empty refs")
    paths = set(refs.file_paths)
    if refs.qualified_names:
        stmt = select(Node.file_path).distinct().where(
            Node.repository_id == repository_id,
            Node.qualified_name.in_(refs.qualified_names),
            Node.file_path.is_not(None),
        )
        paths.update((await session.scalars(stmt)).all())
    if not paths:
        return 0, 0, 0
    # coalesce BEFORE least: Postgres' LEAST skips NULLs, so an un-sized file
    # would otherwise count as a full cap instead of 0
    stmt = select(
        func.coalesce(
            func.sum(func.least(func.coalesce(Node.size_bytes, 0), file_cap)), 0
        ),
        func.count(),
        func.count().filter(Node.size_bytes.is_(None)),
    ).where(
        Node.repository_id == repository_id,
        Node.kind == NodeKind.file,
        Node.file_path.in_(paths),
    )
    total, files, missing = (await session.execute(stmt)).one()
    return int(total), int(files), int(missing)
