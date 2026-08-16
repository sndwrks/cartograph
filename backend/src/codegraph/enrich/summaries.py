"""Phase: LLM summaries for symbol/doc nodes, cached on content hash."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from codegraph.config import get_settings
from codegraph.models import Node, Repository
from codegraph.query import enrich as q

from .llm import LLMClient

logger = logging.getLogger(__name__)

SOURCE_LINE_CAP = 200


def _read_source(root: Path, node: Node) -> str | None:
    if node.file_path is None:
        return None
    path = root / node.file_path
    if not path.is_file():
        return None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    if node.kind.value in ("module", "doc", "config"):
        selected = lines
    else:
        start = (node.start_line or 1) - 1
        end = node.end_line or len(lines)
        selected = lines[start:end]
    if len(selected) > SOURCE_LINE_CAP:
        head = selected[: SOURCE_LINE_CAP // 2]
        tail = selected[-SOURCE_LINE_CAP // 2 :]
        selected = [*head, "… (elided) …", *tail]
    return "\n".join(selected)


def _prompt(node: Node, source: str) -> str:
    return (
        f"Summarize the purpose and role of this {node.kind.value} in 1-3 "
        "sentences. Describe what it is for and how it fits into the codebase, "
        "not a line-by-line account. Reply with the summary only.\n\n"
        f"{node.kind.value}: {node.qualified_name}\n\n```\n{source}\n```"
    )


async def run(
    session: AsyncSession,
    repo: Repository,
    llm: LLMClient,
    limit: int | None = None,
) -> dict:
    min_lines = get_settings().SUMMARY_MIN_LINES
    nodes = await q.nodes_needing_summary(session, repo.id, min_lines, limit)
    root = Path(repo.root_path)
    summarized = failed = skipped = 0
    for node in nodes:
        source = _read_source(root, node)
        if source is None:
            skipped += 1
            continue
        try:
            summary = await llm.complete(_prompt(node, source), max_tokens=300)
        except Exception:
            logger.exception("summary failed for %s", node.qualified_name)
            failed += 1
            continue
        if summary:
            await q.set_summary(session, node.id, summary, node.content_hash)
            summarized += 1
        else:
            failed += 1
    await session.commit()
    return {"summarized": summarized, "failed": failed, "skipped": skipped}
