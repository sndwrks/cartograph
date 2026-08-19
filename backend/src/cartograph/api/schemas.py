"""Shared response shapes for the API and MCP serialization (slices 07/08)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from cartograph.models import (
    Agent,
    AgentMessage,
    Community,
    CommunityEdge,
    Edge,
    IngestRun,
    KnowledgeEntry,
    Node,
)


class NodeOut(BaseModel):
    id: int
    kind: str
    name: str
    qualified_name: str
    file_path: str | None
    start_line: int | None
    end_line: int | None
    summary: str | None
    pagerank: float
    degree_in: int
    degree_out: int
    community_id: int | None

    @classmethod
    def from_node(cls, node: Node) -> NodeOut:
        return cls(
            id=node.id,
            kind=node.kind.value,
            name=node.name,
            qualified_name=node.qualified_name,
            file_path=node.file_path,
            start_line=node.start_line,
            end_line=node.end_line,
            summary=node.summary,
            pagerank=node.pagerank,
            degree_in=node.degree_in,
            degree_out=node.degree_out,
            community_id=node.community_id,
        )


class EdgeOut(BaseModel):
    src_id: int
    dst_id: int
    rel: str
    confidence: str  # always the string value, never omitted
    src_line: int | None

    @classmethod
    def from_edge(cls, edge: Edge) -> EdgeOut:
        return cls(
            src_id=edge.src_id,
            dst_id=edge.dst_id,
            rel=edge.rel.value,
            confidence=edge.confidence.value,
            src_line=edge.src_line,
        )


class CommunityOut(BaseModel):
    id: int
    label: str | None
    summary: str | None
    node_count: int
    internal_edge_count: int

    @classmethod
    def from_community(cls, community: Community) -> CommunityOut:
        return cls(
            id=community.id,
            label=community.label,
            summary=community.summary,
            node_count=community.node_count,
            internal_edge_count=community.internal_edge_count,
        )


class CommunityEdgeOut(BaseModel):
    src_community_id: int
    dst_community_id: int
    weight: int

    @classmethod
    def from_community_edge(cls, edge: CommunityEdge) -> CommunityEdgeOut:
        return cls(
            src_community_id=edge.src_community_id,
            dst_community_id=edge.dst_community_id,
            weight=edge.weight,
        )


class StubEdgeOut(BaseModel):
    """Aggregated edge from a rendered node into a neighboring community."""

    src_id: int
    dst_community_id: int
    weight: int


class ImpactItem(BaseModel):
    node: NodeOut
    depth: int
    via: EdgeOut


class SearchResult(BaseModel):
    node: NodeOut
    score: float
    source: str  # "text" | "semantic" | "hybrid"


class KBEntryOut(BaseModel):
    id: int
    type: str
    slug: str
    title: str
    body: str
    aliases: list[str] | None
    payload: dict
    status: str
    review_note: str | None
    seq: int | None
    repository_id: int | None
    #: The repository NAME. repository_id alone is useless to a client that
    #: only ever knows names, which left the SPA guessing an entry's scope.
    repository: str | None
    source: str | None
    created_by: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # LEGACY, emitted so the SPA and existing clients keep working unchanged
    # while the typed KB lands. Drop with the `category` column once the
    # frontend has moved to type/title/body/payload.
    term: str
    definition: str
    category: str | None

    @classmethod
    def from_entry(
        cls, entry: KnowledgeEntry, repository: str | None = None
    ) -> KBEntryOut:
        return cls(
            id=entry.id,
            type=entry.type,
            slug=entry.slug,
            title=entry.title,
            body=entry.body,
            aliases=entry.aliases,
            payload=entry.payload or {},
            status=entry.status,
            review_note=entry.review_note,
            seq=entry.seq,
            repository_id=entry.repository_id,
            repository=repository,
            source=entry.source,
            created_by=entry.created_by,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            term=entry.title,
            definition=entry.body,
            category=entry.category,
        )


class KBTypeOut(BaseModel):
    """Registry introspection — the endpoint that stops the SPA hard-coding
    the five type names."""

    name: str
    label: str
    lookup_keys: list[str]
    assigns_seq: bool
    export_dir: str | None
    payload_schema: dict
    payload_fields: dict[str, str]


class AgentOut(BaseModel):
    id: int
    name: str
    role: str | None
    status: str
    metadata_json: dict | None
    last_seen: datetime.datetime | None
    created_at: datetime.datetime

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentOut:
        return cls(
            id=agent.id,
            name=agent.name,
            role=agent.role,
            status=agent.status,
            metadata_json=agent.metadata_json,
            last_seen=agent.last_seen,
            created_at=agent.created_at,
        )


class MessageOut(BaseModel):
    id: int
    agent_id: int
    thread_id: int | None
    subject: str | None
    body: str
    node_id: int | None
    created_at: datetime.datetime

    @classmethod
    def from_message(cls, message: AgentMessage) -> MessageOut:
        return cls(
            id=message.id,
            agent_id=message.agent_id,
            thread_id=message.thread_id,
            subject=message.subject,
            body=message.body,
            node_id=message.node_id,
            created_at=message.created_at,
        )


class ThreadRootOut(BaseModel):
    message: MessageOut
    reply_count: int
    last_activity: datetime.datetime


class IngestRunOut(BaseModel):
    id: int
    repository: str
    trigger: str
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    stats: dict | None
    error: str | None = None

    @classmethod
    def from_run(cls, run: IngestRun, repository: str, include_error: bool = False) -> IngestRunOut:
        return cls(
            id=run.id,
            repository=repository,
            trigger=run.trigger,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            stats=run.stats,
            error=run.error if include_error else None,
        )
