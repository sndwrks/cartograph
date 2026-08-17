"""Queries backing the ingest pipeline (slice 05)."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from codegraph.models import Edge, EdgeRel, IngestRun, Node, NodeKind, Repository


async def get_repository_by_name(session: AsyncSession, name: str) -> Repository | None:
    return await session.scalar(select(Repository).where(Repository.name == name))


async def upsert_repository(
    session: AsyncSession, name: str, root_path: str, default_branch: str = "main"
) -> Repository:
    repo = await get_repository_by_name(session, name)
    if repo is None:
        repo = Repository(name=name, root_path=root_path, default_branch=default_branch)
        session.add(repo)
    else:
        repo.root_path = root_path
        repo.default_branch = default_branch
    await session.flush()
    return repo


async def load_file_hashes(session: AsyncSession, repository_id: int) -> dict[str, str]:
    """qualified_name (repo-relative path) -> content_hash for file nodes."""
    rows = await session.execute(
        select(Node.qualified_name, Node.content_hash).where(
            Node.repository_id == repository_id, Node.kind == NodeKind.file
        )
    )
    return dict(rows.all())


async def load_symbol_rows(
    session: AsyncSession, repository_id: int
) -> list[tuple[str, str, str]]:
    """(qualified_name, kind value, name) for every non-file node."""
    rows = await session.execute(
        select(Node.qualified_name, Node.kind, Node.name).where(
            Node.repository_id == repository_id, Node.kind != NodeKind.file
        )
    )
    return [(qname, kind.value, name) for qname, kind, name in rows.all()]


async def load_symbol_locations(
    session: AsyncSession, repository_id: int
) -> dict[tuple[str, str], str | None]:
    """(qualified_name, kind value) -> file_path, for duplicate-qname warnings."""
    rows = await session.execute(
        select(Node.qualified_name, Node.kind, Node.file_path).where(
            Node.repository_id == repository_id, Node.kind != NodeKind.file
        )
    )
    return {(qname, kind.value): path for qname, kind, path in rows.all()}


async def dependent_file_paths(
    session: AsyncSession, repository_id: int, paths: Iterable[str]
) -> set[str]:
    """Files with an edge into any node belonging to the given paths."""
    paths = list(paths)
    if not paths:
        return set()
    src, dst = aliased(Node), aliased(Node)
    rows = await session.execute(
        select(src.file_path)
        .distinct()
        .select_from(Edge)
        .join(src, Edge.src_id == src.id)
        .join(dst, Edge.dst_id == dst.id)
        .where(
            dst.repository_id == repository_id,
            dst.file_path.in_(paths),
            src.repository_id == repository_id,
            src.file_path.is_not(None),
            src.file_path.notin_(paths),
        )
    )
    return {path for (path,) in rows.all()}


async def delete_nodes_for_path(
    session: AsyncSession, repository_id: int, path: str
) -> int:
    result = await session.execute(
        delete(Node).where(Node.repository_id == repository_id, Node.file_path == path)
    )
    return result.rowcount or 0


# asyncpg binds parameters as int16, so a single statement can carry at most
# 32767 of them; a full ingest of a mid-size repo blows past that in one batch.
# Chunk by row width and leave headroom.
_MAX_BIND_PARAMS = 30000


def _param_chunks(rows: list[dict]) -> Iterable[list[dict]]:
    width = max((len(row) for row in rows), default=1)
    size = max(1, _MAX_BIND_PARAMS // max(1, width))
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def upsert_nodes(
    session: AsyncSession, rows: list[dict]
) -> dict[str, int]:
    """Insert node rows, last-write-wins on (repo, qname, kind). Returns qname -> id."""
    if not rows:
        return {}
    ids: dict[str, int] = {}
    for chunk in _param_chunks(rows):
        ids.update(await _upsert_nodes_chunk(session, chunk))
    return ids


async def _upsert_nodes_chunk(
    session: AsyncSession, rows: list[dict]
) -> dict[str, int]:
    stmt = pg_insert(Node).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["repository_id", "qualified_name", "kind"],
        set_={
            "name": stmt.excluded.name,
            "file_path": stmt.excluded.file_path,
            "start_line": stmt.excluded.start_line,
            "end_line": stmt.excluded.end_line,
            "content_hash": stmt.excluded.content_hash,
            "updated_at": func.now(),
        },
    ).returning(Node.id, Node.qualified_name)
    result = await session.execute(stmt)
    return {qname: node_id for node_id, qname in result.all()}


async def insert_edges_ignore_conflicts(
    session: AsyncSession, rows: list[dict]
) -> int:
    if not rows:
        return 0
    inserted = 0
    for chunk in _param_chunks(rows):
        stmt = pg_insert(Edge).values(chunk).on_conflict_do_nothing(
            index_elements=["src_id", "dst_id", "rel", "src_line"]
        )
        result = await session.execute(stmt)
        inserted += result.rowcount or 0
    return inserted


async def delete_ref_edges_from_paths(
    session: AsyncSession, repository_id: int, paths: Iterable[str]
) -> int:
    """Delete non-contains edges originating in the given files (recomputed)."""
    paths = list(paths)
    if not paths:
        return 0
    src_ids = select(Node.id).where(
        Node.repository_id == repository_id, Node.file_path.in_(paths)
    )
    result = await session.execute(
        delete(Edge).where(Edge.rel != EdgeRel.contains, Edge.src_id.in_(src_ids))
    )
    return result.rowcount or 0


async def node_ids_by_qname(
    session: AsyncSession, repository_id: int
) -> dict[str, int]:
    rows = await session.execute(
        select(Node.qualified_name, Node.id).where(
            Node.repository_id == repository_id, Node.kind != NodeKind.file
        )
    )
    return dict(rows.all())


async def list_runs(
    session: AsyncSession, repo_name: str | None = None, limit: int = 20
) -> list[tuple[IngestRun, str]] | None:
    """(run, repository name) newest first. None if repo_name is unknown."""
    stmt = (
        select(IngestRun, Repository.name)
        .join(Repository, IngestRun.repository_id == Repository.id)
        .order_by(IngestRun.id.desc())
        .limit(limit)
    )
    if repo_name is not None:
        repo = await get_repository_by_name(session, repo_name)
        if repo is None:
            return None
        stmt = stmt.where(IngestRun.repository_id == repo.id)
    return [(run, name) for run, name in (await session.execute(stmt)).all()]


async def get_run(
    session: AsyncSession, run_id: int
) -> tuple[IngestRun, str] | None:
    row = (
        await session.execute(
            select(IngestRun, Repository.name)
            .join(Repository, IngestRun.repository_id == Repository.id)
            .where(IngestRun.id == run_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def create_run(
    session: AsyncSession, repository_id: int, trigger: str = "manual"
) -> IngestRun:
    run = IngestRun(repository_id=repository_id, trigger=trigger, status="running")
    session.add(run)
    await session.flush()
    return run


async def finish_run(
    session: AsyncSession,
    run: IngestRun,
    status: str,
    stats: dict | None = None,
    error: str | None = None,
) -> None:
    run.status = status
    run.stats = stats
    run.error = error
    run.finished_at = await session.scalar(select(func.now()))
    await session.flush()
