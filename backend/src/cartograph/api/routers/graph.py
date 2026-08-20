"""Graph read endpoints (slice 07)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.db import get_session
from cartograph.query import graph as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter()

Confidence = Literal["resolved", "llm_inferred", "name_match"]
Kind = Literal["module", "class", "function", "method", "doc", "config"]


def _found(result, what: str = "resource"):
    if result is None:
        raise HTTPException(status_code=404, detail=f"unknown {what}")
    return result


@router.get("/repos")
async def repos(session: SessionDep) -> dict:
    return {"repos": await q.repositories(session)}


@router.get("/overview")
async def overview(repo: str, session: SessionDep) -> dict:
    return _found(await q.overview(session, repo), "repository")


@router.get("/communities/{community_id}/graph")
async def community_graph(
    community_id: int,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=2500)] = 500,
) -> dict:
    return _found(
        await q.community_graph(session, community_id, limit=limit), "community"
    )


@router.get("/nodes/{node_id}")
async def node_detail(node_id: int, session: SessionDep) -> dict:
    return _found(await q.node_detail(session, node_id), "node")


@router.get("/nodes/{node_id}/related-kb")
async def related_kb(
    node_id: int,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    type: Annotated[list[str] | None, Query()] = None,
) -> dict:
    terms = await q.related_kb(session, node_id, limit, tuple(type) if type else None)
    return {"terms": _found(terms, "node")}


@router.get("/nodes/{node_id}/ego")
async def ego(
    node_id: int,
    session: SessionDep,
    hops: Annotated[int, Query(ge=1, le=3)] = 1,
    limit: Annotated[int, Query(ge=1, le=2500)] = 200,
    min_confidence: Confidence | None = None,
) -> dict:
    return _found(
        await q.ego(
            session, node_id, hops=hops, limit=limit, min_confidence=min_confidence
        ),
        "node",
    )


@router.get("/nodes/{node_id}/impact")
async def impact(
    node_id: int,
    session: SessionDep,
    direction: Literal["upstream", "downstream"] = "upstream",
    max_depth: Annotated[int, Query(ge=1, le=10)] = 5,
    limit: Annotated[int, Query(ge=1, le=2500)] = 500,
) -> dict:
    return _found(
        await q.impact(
            session, node_id, direction=direction, max_depth=max_depth, limit=limit
        ),
        "node",
    )


@router.get("/god-nodes")
async def god_nodes(
    repo: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=2500)] = 20,
    kind: Kind | None = None,
    community_id: int | None = None,
) -> dict:
    nodes = await q.god_nodes(
        session, repo, limit=limit, kind=kind, community_id=community_id
    )
    return {"nodes": _found(nodes, "repository")}
