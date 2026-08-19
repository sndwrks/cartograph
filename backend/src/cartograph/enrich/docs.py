"""Phase: docs/config as graph nodes with llm_inferred references edges."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.extractors.base import hash_content
from cartograph.ingest.walker import denied_dirs
from cartograph.models import NodeKind, Repository
from cartograph.query import enrich as q

from .llm import LLMClient

logger = logging.getLogger(__name__)

DOC_SUFFIXES = {".md", ".adoc"}
CONFIG_SUFFIXES = {".sql", ".toml", ".yaml", ".yml", ".json"}
DOC_TEXT_CAP = 8000


def discover_artifacts(
    root: Path, exclude: Iterable[str] = ()
) -> list[tuple[str, NodeKind]]:
    """(repo-relative posix path, kind) for docs and config artifacts."""
    deny = denied_dirs(exclude)
    results: list[tuple[str, NodeKind]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in deny and not d.startswith(".")
        )
        rel_dir = Path(dirpath).relative_to(root)
        at_root = rel_dir == Path(".")
        config_dir = at_root or "config" in rel_dir.parts[0].lower()
        for filename in sorted(filenames):
            suffix = Path(filename).suffix.lower()
            rel = str(PurePosixPath(rel_dir / filename))
            if suffix in DOC_SUFFIXES:
                results.append((rel, NodeKind.doc))
            elif suffix == ".sql":
                results.append((rel, NodeKind.config))
            elif suffix in CONFIG_SUFFIXES and config_dir:
                results.append((rel, NodeKind.config))
    return results


def _link_prompt(path: str, text: str, candidates: list[tuple[int, str, str]]) -> str:
    candidate_lines = "\n".join(f"- {qname}" for _, _, qname in candidates)
    return (
        "This document belongs to a code repository. From the candidate list, "
        "identify which code entities the document GENUINELY references or "
        "documents (not incidental word matches).\n\n"
        f"Document {path}:\n```\n{text[:DOC_TEXT_CAP]}\n```\n\n"
        f"Candidates:\n{candidate_lines}\n\n"
        'Reply with JSON only: {"references": ["<qualified_name>", ...]} '
        "(empty list if none)."
    )


def _parse_references(text: str) -> list[str]:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        return [str(item) for item in data.get("references", [])]
    except (ValueError, TypeError):
        return []


async def run(
    session: AsyncSession,
    repo: Repository,
    llm: LLMClient,
    limit: int | None = None,
) -> dict:
    root = Path(repo.root_path)
    artifacts = discover_artifacts(root, repo.exclude_dirs)
    if limit is not None:
        artifacts = artifacts[:limit]
    created = updated = unchanged = linked_edges = failed = 0

    candidates = await q.symbol_candidates(session, repo.id)
    candidate_by_qname = {qname: node_id for node_id, _, qname in candidates}

    for rel, kind in artifacts:
        path = root / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        content_hash = hash_content(raw)
        existing = await q.get_artifact_node(session, repo.id, rel, kind)
        if existing is not None and existing.content_hash == content_hash:
            unchanged += 1
            continue
        text = raw.decode(errors="replace")
        node = await q.upsert_artifact_node(
            session,
            repo.id,
            rel,
            kind,
            PurePosixPath(rel).name,
            content_hash,
            text.count("\n") + 1,
        )
        # a changed artifact needs a fresh summary + embedding
        node.summary = None
        node.summary_source_hash = None
        node.embedding = None
        created += 1 if existing is None else 0
        updated += 1 if existing is not None else 0

        if kind == NodeKind.doc and candidates:
            # only offer candidates whose bare name appears in the text
            mentioned = [
                candidate
                for candidate in candidates
                if candidate[1] in text or candidate[2] in text
            ][:60]
            if mentioned:
                try:
                    reply = await llm.complete(
                        _link_prompt(rel, text, mentioned), max_tokens=500
                    )
                    qnames = _parse_references(reply)
                except Exception:
                    logger.exception("doc linking failed for %s", rel)
                    failed += 1
                    qnames = []
                target_ids = [
                    candidate_by_qname[qname]
                    for qname in qnames
                    if qname in candidate_by_qname
                ]
                linked_edges += await q.replace_doc_references(
                    session, node.id, target_ids
                )
    await session.commit()
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "reference_edges": linked_edges,
        "failed": failed,
    }
