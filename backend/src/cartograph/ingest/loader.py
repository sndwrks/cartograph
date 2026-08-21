"""Incremental ingest: extract changed files, persist nodes/edges (slice 05)."""

from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.extractors import get_extractor_for, resolve
from cartograph.extractors.base import FileExtraction, SymbolRecord, hash_content
from cartograph.extractors.ts_context import TsResolutionContext, discover_ts_context
from cartograph.models import EdgeConfidence, EdgeRel, NodeKind, Repository
from cartograph.query import ingest as q

from .walker import denied_dirs, is_excluded, walk_repo

logger = logging.getLogger(__name__)


async def ingest_repo(
    session: AsyncSession,
    repo: Repository,
    files: list[str] | None = None,
    full: bool = False,
    trigger: str = "manual",
) -> dict:
    """Run one ingest, recording an IngestRun row. Raises on failure."""
    run = await q.create_run(session, repo.id, trigger)
    await session.commit()  # the run row must survive a failed ingest
    try:
        stats = await _ingest(session, repo, files, full)
    except Exception:
        await session.rollback()
        await q.finish_run(session, run, "failed", error=traceback.format_exc())
        await session.commit()
        raise
    await q.finish_run(session, run, "succeeded", stats=stats)
    await session.commit()
    return stats


def _extract(
    path: str, source: bytes, context: TsResolutionContext | None = None
) -> FileExtraction:
    extractor = get_extractor_for(path)
    if extractor is None:  # walker/CLI filtering should prevent this
        raise ValueError(f"no extractor for {path}")
    return extractor.extract(path, source, context)


async def _ingest(
    session: AsyncSession, repo: Repository, files: list[str] | None, full: bool
) -> dict:
    timings: dict[str, float] = {}
    root = Path(repo.root_path)
    if not root.is_dir():
        # a missing root must not read as "every file was deleted"
        raise FileNotFoundError(f"repository root not found: {root}")

    # --- walk ------------------------------------------------------------
    t0 = time.monotonic()
    stored_hashes = await q.load_file_hashes(session, repo.id)
    if files is not None:
        deny = denied_dirs(repo.exclude_dirs)
        listed = [str(PurePosixPath(p)) for p in files]
        walked = [
            p
            for p in listed
            if not is_excluded(p, deny)
            and (root / p).is_file()
            and get_extractor_for(p) is not None
        ]
        # a previously ingested file that is now excluded counts as deleted,
        # so hook-driven freshenings clean up after a register --exclude
        deleted = {
            p
            for p in listed
            if p in stored_hashes
            and (not (root / p).is_file() or is_excluded(p, deny))
        }
    else:
        walked = walk_repo(root, repo.exclude_dirs)
        deleted = set(stored_hashes) - set(walked)
    sources = {p: (root / p).read_bytes() for p in walked}
    file_hashes = {p: hash_content(src) for p, src in sources.items()}
    if full:
        changed = list(walked)
    else:
        changed = [p for p in walked if stored_hashes.get(p) != file_hashes[p]]
    timings["walk"] = time.monotonic() - t0

    # --- dependent expansion (query edges BEFORE the delete phase) -------
    affected = set(changed) | deleted
    dependents = await q.dependent_file_paths(session, repo.id, affected) - affected
    # only re-resolvable code files: doc/config nodes also carry edges into
    # changed files, but their references are recomputed by the enrich job
    dependents = {
        p
        for p in dependents
        if (root / p).is_file() and get_extractor_for(p) is not None
    }

    # --- extract ----------------------------------------------------------
    t0 = time.monotonic()
    # the discovery walk (tsconfig/package.json manifests) only pays off for
    # TS/JS files; skip it for pure-Python batches and single-file hook runs
    extract_paths = [*changed, *sorted(dependents)]
    needs_ts_context = any(
        getattr(get_extractor_for(p), "language", None) == "typescript"
        for p in extract_paths
    )
    ts_context = (
        discover_ts_context(root, denied_dirs(repo.exclude_dirs))
        if needs_ts_context
        else None
    )
    changed_extractions = [_extract(p, sources[p], ts_context) for p in changed]
    dependent_extractions = [
        _extract(p, (root / p).read_bytes(), ts_context) for p in sorted(dependents)
    ]
    timings["extract"] = time.monotonic() - t0

    # --- load: per changed file, one transaction --------------------------
    t0 = time.monotonic()
    locations = await q.load_symbol_locations(session, repo.id)
    nodes_added = nodes_deleted = edges_added = 0
    for extraction in changed_extractions:
        added, contains, stale = await _load_file(
            session, repo.id, extraction, file_hashes[extraction.path], locations
        )
        nodes_added += added
        nodes_deleted += stale
        edges_added += contains
        await session.commit()
    for path in sorted(deleted):
        nodes_deleted += await q.delete_nodes_for_path(session, repo.id, path)
        await session.commit()
    timings["load"] = time.monotonic() - t0

    # --- resolve: cross-file pass ----------------------------------------
    t0 = time.monotonic()
    edges_deleted = 0
    resolve_paths = set(changed) | dependents
    if resolve_paths:
        edges_deleted = await q.delete_ref_edges_from_paths(
            session, repo.id, resolve_paths
        )
        symbol_rows = await q.load_symbol_rows(session, repo.id)
        extra_symbols = [
            SymbolRecord(
                kind=kind,
                name=name,
                qualified_name=qname,
                start_line=0,
                end_line=0,
                content_hash="",
            )
            for qname, kind, name in symbol_rows
        ]
        candidates = resolve(
            [*changed_extractions, *dependent_extractions], extra_symbols=extra_symbols
        )
        id_map = await q.node_ids_by_qname(session, repo.id)
        edge_rows = []
        for ce in candidates:
            src_id = id_map.get(ce.src_qname)
            dst_id = id_map.get(ce.dst_qname)
            if src_id is None or dst_id is None:
                continue
            edge_rows.append(
                {
                    "src_id": src_id,
                    "dst_id": dst_id,
                    "rel": EdgeRel(ce.rel),
                    "confidence": EdgeConfidence(ce.confidence),
                    "src_line": ce.line,
                }
            )
        edges_added += await q.insert_edges_ignore_conflicts(session, edge_rows)
        await session.commit()
    timings["resolve"] = time.monotonic() - t0

    return {
        "files_seen": len(walked),
        "files_changed": len(changed),
        "files_dependent": len(dependents),
        "nodes_added": nodes_added,
        "nodes_deleted": nodes_deleted,
        "edges_added": edges_added,
        "edges_deleted": edges_deleted,
        "timings": {k: round(v, 3) for k, v in timings.items()},
    }


async def _load_file(
    session: AsyncSession,
    repository_id: int,
    extraction: FileExtraction,
    file_hash: str,
    locations: dict[tuple[str, str], str | None],
) -> tuple[int, int, int]:
    """Upsert the file node, symbol nodes, and contains edges, then prune
    symbols the extraction no longer produces. Upsert-then-prune (rather than
    delete-then-insert) keeps node ids stable across re-ingest so paid-for
    summaries and embeddings survive. Returns (inserted, contains, stale) —
    inserted counts genuinely new nodes, not conflicted updates."""
    rows = [
        {
            "repository_id": repository_id,
            "kind": NodeKind.file,
            "name": PurePosixPath(extraction.path).name,
            "qualified_name": extraction.path,
            "file_path": extraction.path,
            "start_line": None,
            "end_line": None,
            "content_hash": file_hash,
        }
    ]
    for sym in extraction.symbols:
        key = (sym.qualified_name, sym.kind)
        previous = locations.get(key)
        if previous is not None and previous != extraction.path:
            logger.warning(
                "duplicate qualified name %s (%s): %s overwrites %s",
                sym.qualified_name,
                sym.kind,
                extraction.path,
                previous,
            )
        locations[key] = extraction.path
        rows.append(
            {
                "repository_id": repository_id,
                "kind": NodeKind(sym.kind),
                "name": sym.name,
                "qualified_name": sym.qualified_name,
                "file_path": extraction.path,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "content_hash": sym.content_hash,
            }
        )
    ids, inserted = await q.upsert_nodes(session, rows)
    stale = await q.delete_stale_nodes_for_path(
        session,
        repository_id,
        extraction.path,
        {(row["qualified_name"], row["kind"].value) for row in rows},
    )

    # contains edges: file -> module, then each symbol under its qname parent
    # (module -> top-level, class -> methods/nested)
    edge_rows = []
    file_id = ids[extraction.path]
    module_id = ids.get(extraction.module_qname)
    if module_id is not None:
        edge_rows.append((file_id, module_id))
    for sym in extraction.symbols:
        if sym.kind == "module":
            continue
        parent_qname = sym.qualified_name.rsplit(".", 1)[0]
        parent_id = ids.get(parent_qname)
        child_id = ids.get(sym.qualified_name)
        if parent_id is not None and child_id is not None and parent_id != child_id:
            edge_rows.append((parent_id, child_id))
    contains = await q.insert_edges_ignore_conflicts(
        session,
        [
            {
                "src_id": src,
                "dst_id": dst,
                "rel": EdgeRel.contains,
                "confidence": EdgeConfidence.resolved,
                "src_line": None,
            }
            for src, dst in edge_rows
        ],
    )
    return inserted, contains, stale
