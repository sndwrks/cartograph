"""Phase: LLM labels + summaries for communities."""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import Repository
from cartograph.query import enrich as q

from .llm import LLMClient

logger = logging.getLogger(__name__)


def _prompt(members: list, neighbor_labels: list[str]) -> str:
    member_lines = "\n".join(
        f"- {node.qualified_name} ({node.kind.value})"
        + (f": {node.summary}" if node.summary else "")
        for node in members
    )
    neighbors = ", ".join(neighbor_labels) if neighbor_labels else "none labeled yet"
    return (
        "These code entities form one community (cluster) in a codebase "
        "knowledge graph. Name it.\n\n"
        f"Members (by importance):\n{member_lines}\n\n"
        f"Neighboring communities: {neighbors}\n\n"
        'Reply with JSON only: {"label": "<2-4 word name, e.g. Payments '
        'pipeline>", "summary": "<1-2 sentence description>"}'
    )


def _parse(text: str) -> tuple[str, str] | None:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        label = str(data["label"]).strip()
        summary = str(data.get("summary", "")).strip()
        if label:
            return label, summary
    except (ValueError, KeyError, TypeError):
        pass
    return None


async def run(
    session: AsyncSession,
    repo: Repository,
    llm: LLMClient,
    force: bool = False,
    limit: int | None = None,
) -> dict:
    communities = await q.communities_needing_label(session, repo.id, force)
    if limit is not None:
        communities = communities[:limit]
    labeled = failed = 0
    for community in communities:
        members = await q.community_top_members(session, community.id)
        if not members:
            continue
        neighbors = await q.community_neighbor_labels(session, community.id)
        try:
            text = await llm.complete(_prompt(members, neighbors), max_tokens=200)
        except Exception:
            logger.exception("labeling failed for community %d", community.id)
            failed += 1
            continue
        parsed = _parse(text)
        if parsed is None:
            logger.warning("unparseable label response for community %d", community.id)
            failed += 1
            continue
        await q.set_community_label(session, community.id, parsed[0], parsed[1])
        labeled += 1
    await session.commit()
    return {"labeled": labeled, "failed": failed}
