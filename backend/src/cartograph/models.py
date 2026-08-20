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
    # directory basenames pruned from every walk (ingest + docs enrich), on
    # top of the built-in deny-list — set via `ingest register --exclude`
    exclude_dirs: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'")
    )
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
    """A typed knowledge-base entry (slice 15).

    `type` is a key into `cartograph.kb.types.REGISTRY` and is deliberately
    `Text`, not `sa.Enum`: adding a type must never require an `ALTER TYPE`
    (and see the enum name-vs-value gotcha above). Validation happens in
    `query/kb.py` against the registry.
    """

    __tablename__ = "knowledge_base"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(Text)          # registry key
    slug: Mapped[str] = mapped_column(Text)          # identity + export filename stem
    title: Mapped[str] = mapped_column(Text)         # was: term — "PSN"
    body: Mapped[str] = mapped_column(Text)          # was: definition
    aliases: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    payload: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'published'"), default="published"
    )  # proposed | published | rejected | archived
    review_note: Mapped[Optional[str]] = mapped_column(Text)  # the human's reason on reject
    seq: Mapped[Optional[int]] = mapped_column(Integer)  # ADR number; NULL when unnumbered
    repository_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )  # NULL = global, visible to every repo
    # LEGACY glossary sub-tag (acronym | domain | convention), superseded by
    # `type`. Kept so ?category= and RelatedKbTerm keep working; drop once the
    # SPA has moved to type/title/body/payload.
    category: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(Text)  # api | mcp | cli | seed | legacy
    created_by: Mapped[Optional[str]] = mapped_column(Text)  # "human:john" | "agent:<name>"
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Identity, and the direct descendant of the old ix_kb_term_lower.
        # coalesce(repository_id, 0) rather than the bare column because a
        # plain multi-column unique index treats NULLs as distinct, which
        # would let two global "PSN" rows coexist.
        Index(
            "ix_kb_ident",
            text("coalesce(repository_id, 0)"), text("type"), text("lower(slug)"),
            unique=True, postgresql_where=text("status = 'published'"),
        ),
        # THE DETERMINISM GUARANTEE. Within type='glossary' and
        # repository_id IS NULL this is exactly the old ix_kb_term_lower, which
        # is what keeps the PSN contract intact. Partial on `published` so an
        # agent can propose a competing definition; the 409 moves to publish.
        Index(
            "ix_kb_title_lower",
            text("coalesce(repository_id, 0)"), text("type"), text("lower(title)"),
            unique=True, postgresql_where=text("status = 'published'"),
        ),
        Index(
            "ix_kb_seq",
            text("coalesce(repository_id, 0)"), text("type"), "seq",
            unique=True, postgresql_where=text("seq IS NOT NULL"),
        ),
        Index("ix_kb_type_status", "type", "status"),
        Index("ix_kb_embedding_hnsw", "embedding",
              postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class EnrichBatch(Base):
    """One Anthropic Message Batch submitted by `enrich --batch` (summaries).

    Rows are the resume state for the batch workflow: submit inserts one row
    per provider batch and exits; status/collect pick up from here in a later
    process. A row is created (status `submitting`, no provider id yet) BEFORE
    the provider call and updated after it returns, so a crash or lost
    response between the two leaves visible evidence instead of an invisible
    paid batch. Failed, expired, or stale results are only counted in
    `stats` — the summaries predicate (summary IS NULL OR hash mismatch)
    re-selects those nodes on the next sync run, so nothing is lost by
    skipping them.
    """

    __tablename__ = "enrich_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(Text, default="summaries")
    # NULL only while status is `submitting` (intent recorded, provider call
    # not yet acknowledged)
    provider_batch_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(
        Text, default="submitting"
    )  # submitting | submitted | ended | collected | canceled | abandoned
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    # candidate nodes are iterated in id order, so each batch covers a
    # contiguous id span — a forced resubmit skips nodes inside open spans
    # instead of paying for them twice
    node_id_min: Mapped[Optional[int]] = mapped_column(BigInteger)
    node_id_max: Mapped[Optional[int]] = mapped_column(BigInteger)
    counts: Mapped[Optional[dict]] = mapped_column(JSONB)  # provider request_counts
    stats: Mapped[Optional[dict]] = mapped_column(JSONB)   # collect outcome
    error: Mapped[Optional[str]] = mapped_column(Text)
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))


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
