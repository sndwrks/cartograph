"""Knowledge-base endpoints (slices 08/15/16)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from cartograph.api.schemas import KBEntryOut, KBTypeOut
from cartograph.models import Repository
from cartograph.db import get_session
from cartograph.kb.types import DEFAULT_TYPE, REGISTRY, LOOKUP_PRECEDENCE
from cartograph.query import ingest as q_ingest
from cartograph.query import kb as q

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/kb")


class KBCreate(BaseModel):
    """Accepts both vocabularies.

    `term`/`definition` are the pre-typed names, kept as deprecated aliases so
    existing clients (and the slice-08 test suite) keep working byte for byte.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = DEFAULT_TYPE
    title: str | None = None
    term: str | None = None  # DEPRECATED alias for title
    body: str | None = None
    definition: str | None = None  # DEPRECATED alias for body
    slug: str | None = None
    aliases: list[str] | None = None
    payload: dict | None = None
    category: str | None = None
    repository: str | None = None  # repo NAME; null = global
    status: Literal["proposed", "published"] = "published"
    created_by: str | None = None

    @model_validator(mode="after")
    def _exactly_one_of_each(self) -> KBCreate:
        if (self.title is None) == (self.term is None):
            raise ValueError("provide exactly one of 'title' or 'term'")
        if (self.body is None) == (self.definition is None):
            raise ValueError("provide exactly one of 'body' or 'definition'")
        return self

    @property
    def resolved_title(self) -> str:
        return self.title if self.title is not None else self.term  # type: ignore[return-value]

    @property
    def resolved_body(self) -> str:
        return self.body if self.body is not None else self.definition  # type: ignore[return-value]


class KBUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    title: str | None = None
    term: str | None = None  # DEPRECATED alias for title
    body: str | None = None
    definition: str | None = None  # DEPRECATED alias for body
    slug: str | None = None
    aliases: list[str] | None = None
    payload: dict | None = None
    category: str | None = None
    # Present so the SPA's scope selector actually works on edit. Without it
    # pydantic's default extra="ignore" dropped the field and answered 200,
    # telling the human their change had been saved when it had not.
    repository: str | None = None

    def to_fields(self) -> dict:
        fields = self.model_dump(exclude_unset=True)
        if (term := fields.pop("term", None)) is not None:
            fields.setdefault("title", term)
        if (definition := fields.pop("definition", None)) is not None:
            fields.setdefault("body", definition)
        return fields


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replaces_id: int | None = None


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str

    @model_validator(mode="after")
    def _reason_is_real(self) -> RejectBody:
        # An unexplained rejection teaches the next agent nothing, and the
        # reason is exactly what kb_propose reads back on a re-proposal.
        if not self.reason.strip():
            raise ValueError("a rejection reason is required")
        return self


async def _repository_names(
    session: AsyncSession, entries: list
) -> dict[int, str]:
    """id -> name for every repository the given entries are scoped to."""
    ids = {e.repository_id for e in entries if e.repository_id is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(Repository.id, Repository.name).where(Repository.id.in_(sorted(ids)))
    )
    return dict(rows.all())


async def _out(session: AsyncSession, entry) -> KBEntryOut:
    names = await _repository_names(session, [entry])
    return KBEntryOut.from_entry(entry, names.get(entry.repository_id))


async def _repository_id(session: AsyncSession, name: str | None) -> int | None:
    if name is None:
        return None
    repo = await q_ingest.get_repository_by_name(session, name)
    if repo is None:
        raise HTTPException(status_code=422, detail=f"unknown repository: {name}")
    return repo.id


def _duplicate(exc: q.DuplicateTermError) -> HTTPException:
    detail = f"already exists in this type and scope: {exc.value}"
    if exc.existing_id is not None:
        detail = f"{detail} (id {exc.existing_id})"
    return HTTPException(status_code=409, detail=detail)


def _payload_invalid(exc: q.PayloadValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.errors)


# --- collection routes ----------------------------------------------------
# /types, /lookup and /propose MUST stay above /{entry_id}: a bare path
# segment would otherwise be captured as an entry id.


@router.post("", status_code=201)
async def create(body: KBCreate, session: SessionDep) -> KBEntryOut:
    return await _create(body, session, status=body.status)


@router.post("/propose", status_code=201)
async def propose(body: KBCreate, session: SessionDep) -> KBEntryOut:
    """The API twin of the kb_propose MCP tool: status is forced."""
    return await _create(body, session, status=q.PROPOSED, source="api")


async def _create(
    body: KBCreate, session: AsyncSession, *, status: str, source: str = "api"
) -> KBEntryOut:
    repository_id = await _repository_id(session, body.repository)
    try:
        entry = await q.create_entry(
            session,
            body.resolved_title,
            body.resolved_body,
            body.aliases,
            body.category,
            type=body.type,
            slug=body.slug,
            payload=body.payload,
            repository_id=repository_id,
            status=status,
            source=source,
            created_by=body.created_by,
        )
    except q.UnknownKbTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except q.PayloadValidationError as exc:
        raise _payload_invalid(exc) from None
    except q.DuplicateTermError as exc:
        raise _duplicate(exc) from None
    await session.commit()
    await session.refresh(entry)
    return await _out(session, entry)


@router.get("")
async def list_(
    session: SessionDep,
    category: str | None = None,
    type: str | None = None,
    status: str | None = q.PUBLISHED,
    repo: str | None = None,
    q_: Annotated[str | None, Query(alias="q")] = None,
    # Raised from slice 08's 200: the review queue pulls published entries in
    # one shot to pair each proposal with the entry it would replace, and a
    # cap it can silently hit turns "no incumbent" into a wrong side-by-side.
    # `total` still comes back, so a caller can tell when it has been clipped.
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    repo_filter: q.RepoFilter = "*"
    if repo is not None:
        repo_filter = await _repository_id(session, repo)
    entries = await q.list_entries(
        session,
        category,
        limit,
        offset,
        type=type,
        status=status,
        repo_filter=repo_filter,
        q=q_,
    )
    total = await q.count_entries(
        session,
        category,
        type=type,
        status=status,
        repo_filter=repo_filter,
        q=q_,
    )
    names = await _repository_names(session, entries)
    return {
        "entries": [
            KBEntryOut.from_entry(e, names.get(e.repository_id)) for e in entries
        ],
        "total": total,
    }


@router.get("/types")
async def types() -> dict:
    return {
        "types": [
            KBTypeOut(
                name=t.name,
                label=t.label,
                lookup_keys=list(t.lookup_keys),
                assigns_seq=t.assigns_seq,
                export_dir=t.export_dir,
                payload_schema=t.Payload.model_json_schema(),
                payload_fields=t.payload_fields(),
            )
            for t in (REGISTRY[name] for name in LOOKUP_PRECEDENCE)
        ]
    }


@router.get("/lookup")
async def lookup(
    term: Annotated[str, Query(min_length=1)],
    session: SessionDep,
    type: str | None = None,
    repo: str | None = None,
) -> dict:
    repo_filter: q.RepoFilter = "*"
    if repo is not None:
        repo_filter = await _repository_id(session, repo)
    try:
        result = await q.lookup(session, term, type=type, repo_filter=repo_filter)
    except q.UnknownKbTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    names = await _repository_names(
        session, [*result["results"], *result["also_matched"]]
    )
    out = {
        "match": result["match"],
        "results": [
            KBEntryOut.from_entry(e, names.get(e.repository_id))
            for e in result["results"]
        ],
    }
    # `{match, results}` is the frozen top level of this response — two tests
    # assert exact dict equality on the "none" case, so anything additive has
    # to stay out unless it is actually carrying something.
    if result["also_matched"]:
        out["also_matched"] = [
            KBEntryOut.from_entry(e, names.get(e.repository_id))
            for e in result["also_matched"]
        ]
    return out


# --- item routes ----------------------------------------------------------


@router.get("/{entry_id}")
async def read(entry_id: int, session: SessionDep) -> KBEntryOut:
    entry = await q.get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown kb entry")
    return await _out(session, entry)


@router.put("/{entry_id}")
async def update(entry_id: int, body: KBUpdate, session: SessionDep) -> KBEntryOut:
    fields = body.to_fields()
    if "repository" in fields:
        # the wire carries a repo NAME; the column is an id
        fields["repository_id"] = await _repository_id(session, fields.pop("repository"))
    try:
        entry = await q.update_entry(session, entry_id, fields)
    except q.UnknownKbTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except q.PayloadValidationError as exc:
        raise _payload_invalid(exc) from None
    except q.DuplicateTermError as exc:
        raise _duplicate(exc) from None
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown kb entry")
    await session.commit()
    # updated_at is a server-side onupdate default: refresh it explicitly, a
    # lazy attribute load would attempt sync IO on the async connection
    await session.refresh(entry)
    return await _out(session, entry)


@router.delete("/{entry_id}", status_code=204)
async def delete(entry_id: int, session: SessionDep) -> None:
    if not await q.delete_entry(session, entry_id):
        raise HTTPException(status_code=404, detail="unknown kb entry")
    await session.commit()


async def _transition(
    entry_id: int, session: AsyncSession, status: str, **kwargs
) -> KBEntryOut:
    try:
        entry = await q.set_status(session, entry_id, status, **kwargs)
    except q.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except q.DuplicateTermError as exc:
        raise _duplicate(exc) from None
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown kb entry")
    await session.commit()
    await session.refresh(entry)
    return await _out(session, entry)


@router.post("/{entry_id}/publish")
async def publish(entry_id: int, body: PublishBody, session: SessionDep) -> KBEntryOut:
    return await _transition(
        entry_id, session, q.PUBLISHED, replaces_id=body.replaces_id
    )


@router.post("/{entry_id}/reject")
async def reject(entry_id: int, body: RejectBody, session: SessionDep) -> KBEntryOut:
    return await _transition(entry_id, session, q.REJECTED, reason=body.reason)


@router.post("/{entry_id}/archive")
async def archive(entry_id: int, session: SessionDep) -> KBEntryOut:
    return await _transition(entry_id, session, q.ARCHIVED)
