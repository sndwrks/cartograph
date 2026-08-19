"""Shared FastAPI dependencies (slice 19)."""

from __future__ import annotations

from fastapi import HTTPException, Request


def no_unknown_query_params(request: Request) -> None:
    """Refuse a query param the endpoint does not declare.

    An ignored filter is worse than a rejected one: an unscoped read that looks
    scoped answers "nothing is claimed here" for the whole board.
    """
    declared = {p.alias for p in request.scope["route"].dependant.query_params}
    unknown = sorted(set(request.query_params.keys()) - declared)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown query parameter(s): {', '.join(unknown)}",
        )
