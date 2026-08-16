"""Shared response shapes for the API and MCP serialization (slices 07/08)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from codegraph.models import (
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
    term: str
    definition: str
    aliases: list[str] | None
    category: str | None  # acronym | domain | convention
    updated_at: datetime.datetime

    @classmethod
    def from_entry(cls, entry: KnowledgeEntry) -> KBEntryOut:
        return cls(
            id=entry.id,
            term=entry.term,
            definition=entry.definition,
            aliases=entry.aliases,
            category=entry.category,
            updated_at=entry.updated_at,
        )


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
