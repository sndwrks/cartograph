from __future__ import annotations

import datetime
import enum
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBED_DIM = 1024


class Base(DeclarativeBase):
    pass


class NodeKind(enum.Enum):
    file = "file"
    module = "module"
    class_ = "class"
    function = "function"
    method = "method"
    doc = "doc"
    config = "config"


class EdgeRel(enum.Enum):
    imports = "imports"
    calls = "calls"
    inherits = "inherits"
    references = "references"
    contains = "contains"


class EdgeConfidence(enum.Enum):
    resolved = "resolved"        # tier 1 import-proven or tier 2 analyzer-proven
    llm_inferred = "llm_inferred"  # tier 3 model judgment
    name_match = "name_match"    # tier 1 syntactic fallback


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    root_path: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(Text, default="main")
    last_ingested_commit: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    nodes: Mapped[list[Node]] = relationship(back_populates="repository")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    # NOTE: sa.Enum(NodeKind) stores member *names* — the DB label for
    # NodeKind.class_ is 'class_', not 'class'. Always go through the ORM enum
    # type (or use 'class_' in raw SQL literals).
    kind: Mapped[NodeKind] = mapped_column(Enum(NodeKind, name="node_kind"))
    name: Mapped[str] = mapped_column(Text)
    qualified_name: Mapped[str] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    start_line: Mapped[Optional[int]] = mapped_column(Integer)
    end_line: Mapped[Optional[int]] = mapped_column(Integer)
    content_hash: Mapped[Optional[str]] = mapped_column(Text)  # incremental re-ingest
    summary: Mapped[Optional[str]] = mapped_column(Text)       # tier 3 output
    summary_source_hash: Mapped[Optional[str]] = mapped_column(Text)  # hash summary was made from
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(EMBED_DIM))

    # batch-computed metrics backing the overview and god-node panel
    degree_in: Mapped[int] = mapped_column(Integer, default=0)
    degree_out: Mapped[int] = mapped_column(Integer, default=0)
    pagerank: Mapped[float] = mapped_column(default=0.0)
    community_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("communities.id", ondelete="SET NULL"), index=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship(back_populates="nodes")
    community: Mapped[Optional[Community]] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("repository_id", "qualified_name", "kind"),
        Index("ix_nodes_name_trgm", "name",
              postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("ix_nodes_qname_trgm", "qualified_name",
              postgresql_using="gin",
              postgresql_ops={"qualified_name": "gin_trgm_ops"}),
        Index("ix_nodes_embedding_hnsw", "embedding",
              postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_nodes_pagerank", text("pagerank DESC")),
    )


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    src_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    dst_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    rel: Mapped[EdgeRel] = mapped_column(Enum(EdgeRel, name="edge_rel"))
    confidence: Mapped[EdgeConfidence] = mapped_column(
        Enum(EdgeConfidence, name="edge_confidence")
    )
    src_line: Mapped[Optional[int]] = mapped_column(Integer)  # call/ref site

    src: Mapped[Node] = relationship(foreign_keys=[src_id])
    dst: Mapped[Node] = relationship(foreign_keys=[dst_id])

    __table_args__ = (
        UniqueConstraint("src_id", "dst_id", "rel", "src_line"),
        Index("ix_edges_dst_rel", "dst_id", "rel"),
        Index("ix_edges_src_rel", "src_id", "rel"),
    )


class Community(Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[Optional[str]] = mapped_column(Text)    # tier-3 LLM-written name
    summary: Mapped[Optional[str]] = mapped_column(Text)  # tier-3 LLM-written blurb
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    internal_edge_count: Mapped[int] = mapped_column(Integer, default=0)
    algorithm: Mapped[str] = mapped_column(Text, default="leiden")

    nodes: Mapped[list[Node]] = relationship(back_populates="community")


class CommunityEdge(Base):
    """Aggregated inter-community edges backing the overview render."""
    __tablename__ = "community_edges"

    src_community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id", ondelete="CASCADE"), primary_key=True
    )
    dst_community_id: Mapped[int] = mapped_column(
        ForeignKey("communities.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=0)  # underlying edge count


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="idle")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_seen: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    messages: Mapped[list[AgentMessage]] = relationship(back_populates="agent")


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE"), index=True
    )  # null = thread root; self-reference keeps threading flat and simple
    subject: Mapped[Optional[str]] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    node_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL")
    )  # optional anchor: "this message is about this symbol"
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    agent: Mapped[Agent] = relationship(back_populates="messages")


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    term: Mapped[str] = mapped_column(Text)          # "PSN"
    definition: Mapped[str] = mapped_column(Text)    # "PositageNet — never any other expansion"
    aliases: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    category: Mapped[Optional[str]] = mapped_column(Text)  # acronym | domain | convention
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(EMBED_DIM))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_kb_term_lower", func.lower(text("term")), unique=True),
        Index("ix_kb_embedding_hnsw", "embedding",
              postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(Text, default="manual")  # manual | hook | ci
    status: Mapped[str] = mapped_column(Text, default="running")  # running | succeeded | failed
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    stats: Mapped[Optional[dict]] = mapped_column(JSONB)  # per-phase timings, node/edge deltas
    error: Mapped[Optional[str]] = mapped_column(Text)
