# CodeGraph — Technical Specification

**Version 0.1 · August 2026**

A self-hosted codebase knowledge graph: Python/FastAPI backend, Postgres 18 + pgvector storage, React 19 SPA, MCP server for AI-assistant access, initial graph generation driven by Claude Code. Everything runs via Docker Compose; the database is reachable only on the internal compose network.

---

## 1. Goals and non-goals

The system ingests one or more repositories and produces a persistent, queryable graph of code entities (files, classes, functions) and their relationships (imports, calls, inheritance, references), enriched with vector embeddings over LLM-written summaries. It additionally hosts a company knowledge base of terms and definitions (e.g. "PSN" resolves to PositageNet and nothing else), an agents registry, and a message board that agents use to coordinate. Humans consume the graph through a React SPA; AI assistants consume it through an MCP server backed by the same query layer.

Non-goals for v0.1: multi-tenant auth, hosted deployment, real-time collaborative editing of the graph, IDE plugins, and languages beyond the ones the team actually uses. Precision-perfect call resolution is explicitly not required at tier 1 — the confidence model (section 3) exists so downstream consumers can weigh edges appropriately rather than trusting them blindly.

## 2. Stack and runtime

Python 3.14 managed with uv (single `pyproject.toml`, `uv.lock` committed). FastAPI for the HTTP API, SQLAlchemy 2.0 in fully typed declarative style as the ORM, Alembic for migrations generated from the models. Postgres 18 with the pgvector extension, using the `pgvector/pgvector:pg18` image. React 19 with Vite for the SPA. The MCP server is a separate small Python process using the official MCP Python SDK, importing the same query-layer package the API uses so SQL lives in exactly one place.

Compatibility note: Python 3.14 is recent enough that binary wheels occasionally lag. The dependencies that matter here — SQLAlchemy 2.0.4x, asyncpg, tree-sitter bindings, pgvector-python — all publish 3.14 wheels as of mid-2026, but pin versions in `uv.lock` and treat any upgrade of the tree-sitter grammar packages as a change requiring a re-extraction run, since grammar upgrades can shift node types.

### 2.1 Docker Compose topology

Four services on one internal network. **db** runs Postgres 18 with pgvector, no ports published to the host; data persisted in a named volume; healthcheck via `pg_isready`. **api** runs the FastAPI app (uvicorn), depends on db healthy, publishes port 8000 to the host, runs `alembic upgrade head` on startup. **web** serves the built SPA via nginx (or Vite dev server in the dev override file), publishes port 5173/80, proxies `/api` to the api service so the browser never needs direct db or CORS access. **mcp** runs the MCP server over streamable HTTP, publishes its port to the host so Claude Code on the host machine can reach it; it depends on db healthy. Extraction jobs run as one-shot compose commands (`docker compose run api python -m codegraph.ingest ...`) rather than a long-lived worker, since ingestion is batch-oriented. A dev override file mounts source for hot reload. Secrets (db password, Anthropic API key for embedding/summary passes) come from a `.env` file that is gitignored.

The deliberate consequence of not publishing the db port: all human and machine access goes through the API or MCP layer. If ad-hoc SQL is needed during development, use `docker compose exec db psql`.

## 3. Extraction pipeline — three tiers

Extraction is a pipeline where each tier refines the output of the previous one. Every edge carries a `confidence` value recording which tier produced it, and consumers (SPA badges, MCP responses) always surface it.

### Tier 1 — Deterministic AST extraction (tree-sitter)

One extractor module per language in the codebase, built on the official tree-sitter Python bindings and the per-language grammar packages. Each extractor walks the AST of a file and emits symbol records (module, class, function, method, with name, qualified name, line span) and raw reference records (call sites, import statements, inheritance clauses, attribute accesses). Reference resolution at this tier is intentionally naive: match by qualified name against the symbol table, using the file's import graph to narrow candidates. Edges resolved this way are tagged `resolved` when the import graph yields exactly one candidate and `name_match` when the extractor fell back to a same-name match with multiple or zero import-supported candidates. Tier 1 is fast, free, fully local, and re-runs incrementally: each file node stores a content hash, and the ingest job re-extracts only files whose hash changed, deleting and re-inserting their symbols and edges inside one transaction.

### Tier 2 — LSP-assisted resolution (optional, per-language)

For languages where tier-1 ambiguity hurts, the pipeline can invoke the language's real analyzer — pyright for Python, tsserver for TypeScript — or ingest a SCIP index produced by the corresponding open-source indexer. The tier-2 pass upgrades `name_match` edges to `resolved` when the analyzer confirms the target, deletes edges the analyzer refutes, and adds reference edges tier 1 could not see (dynamic dispatch targets the analyzer can prove, re-exports). Tier 2 runs as a separate job so it can be adopted one language at a time; it is not a launch requirement.

### Tier 3 — LLM enrichment (Claude Code / API)

The tier-3 pass does three things. First, it writes a one-to-three-sentence summary for every symbol node above a size threshold, which is what gets embedded — summaries retrieve dramatically better than raw code. Second, it attempts to resolve edges still tagged `name_match` after tiers 1–2, using surrounding source as context; edges it resolves this way are tagged `llm_inferred`, never `resolved`, because the model's answer is a judgment rather than a proof. Third, it reads non-code artifacts — READMEs, ADRs, SQL schema files, config — and links them into the graph as `doc` and `config` nodes with `references` edges to the code entities they mention. Tier 3 is the only pass that costs API money; it caches on content hash so a re-run after a small commit touches only changed nodes. The initial run over a large codebase is invoked from Claude Code, which orchestrates extraction, loading, summarization, and embedding end to end via the ingest CLI.

Confidence vocabulary, in descending trust: `resolved` (proven by import graph or analyzer), `llm_inferred` (model judgment), `name_match` (syntactic coincidence). The MCP server includes the tag on every edge it returns, and the system prompt shipped with the MCP tools instructs assistants to treat `name_match` edges as hints.

## 4. Data model

Embeddings use 1024-dimensional vectors (voyage-3 / voyage-code-3 class models; the dimension is a config constant surfaced in one place so switching models is a migration, not a hunt). Vector columns get HNSW indexes with cosine ops; symbol and term names get trigram GIN indexes for fuzzy text search. Graph metrics needed by the UI — degree, PageRank, community id — are computed in a batch job after ingestion (igraph in-process) and stored on the node row, so the overview and side panel are plain indexed reads with no graph computation at request time.

The complete SQLAlchemy 2.0 models (the only code in this spec):

```python
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
    kind: Mapped[NodeKind] = mapped_column(Enum(NodeKind, name="node_kind"))
    name: Mapped[str] = mapped_column(Text)
    qualified_name: Mapped[str] = mapped_column(Text)
    file_path: Mapped[Optional[str]] = mapped_column(Text)
    start_line: Mapped[Optional[int]] = mapped_column(Integer)
    end_line: Mapped[Optional[int]] = mapped_column(Integer)
    content_hash: Mapped[Optional[str]] = mapped_column(Text)  # incremental re-ingest
    summary: Mapped[Optional[str]] = mapped_column(Text)       # tier 3 output
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
```

(`JSONB` imports from `sqlalchemy.dialects.postgresql`; the `pg_trgm` and `vector` extensions are created in the initial Alembic migration.)

## 5. API surface

All endpoints live under `/api/v1` and return JSON shaped for the SPA. The graph read endpoints are: `GET /overview?repo=` returning communities with their labels, summaries, node counts, and the aggregated community-edge list — this is the entire payload for the overview render; `GET /communities/{id}/graph?limit=` returning the nodes and intra-community edges for the drill-in view, ranked by pagerank and truncated server-side; `GET /nodes/{id}/ego?hops=&limit=&min_confidence=` returning the bounded neighborhood for the ego view; `GET /nodes/{id}` returning full node detail including summary, metrics, and edge counts by relation; `GET /nodes/{id}/impact?direction=&max_depth=` returning reverse-reachability as a depth-annotated tree; `GET /god-nodes?repo=&limit=&kind=` returning top nodes by pagerank (with degree as tiebreak) for the side panel; and `GET /search?q=&mode=` where mode is `hybrid` (default), `text`, or `semantic` — hybrid runs trigram similarity on names and cosine similarity on embeddings and merges with reciprocal rank fusion.

The knowledge base gets standard CRUD at `/kb` plus `GET /kb/lookup?term=` which performs exact/alias match first and only falls back to vector search when no exact hit exists — the PSN case must be deterministic. Agents and the message board get CRUD at `/agents` and `/messages` with thread-scoped listing and an optional `node_id` filter so a thread can be pinned to a symbol. Ingestion status is exposed read-only at `/ingest/runs`.

## 6. MCP server

Seven tools, each a thin wrapper over the shared query layer: `search_code` (hybrid search, returns qualified names, file paths, summaries, scores), `get_node` (detail plus immediate edges with confidence tags), `get_neighbors` (ego query with hop and confidence filters), `impact_of` (blast radius; callers/importers transitively), `kb_lookup` (exact-then-vector, same rule as the API), `post_message` and `read_board` (agent coordination, with agent self-registration on first post). Transport is streamable HTTP on a published port so Claude Code connects from the host. Tool descriptions instruct the model to prefer `kb_lookup` when it encounters unfamiliar acronyms and to treat `name_match` edges as unproven. The repository's `CLAUDE.md` reinforces both behaviors.

## 7. React 19 SPA — the three views

The SPA is a single workspace page with a persistent right side panel and a main canvas that switches between three view modes. State lives in TanStack Query for server data and a small Zustand store for view state (selected node, active community, hop depth, confidence filter). Rendering uses react-force-graph's WebGL renderer; the server-side truncation rules below exist precisely so the client never receives more than roughly 2,500 renderable nodes.

**Overview (landing view).** Renders communities as super-nodes sized by node count, connected by aggregated community edges weighted by underlying edge count, laid out force-directed. Each super-node shows its tier-3 label ("Payments pipeline", "Auth & sessions"). Hovering shows the community summary; clicking drills in. Because the payload is communities and community edges only — typically dozens of items, not thousands — this view is instant and never hairballs.

**Community drill-in.** Clicking a super-node transitions the canvas to that community's internal graph: its top-N nodes by pagerank with intra-community edges, plus ghosted stub edges indicating connections that leave the community (clicking a stub navigates to the neighboring community). Breadcrumb navigation returns to the overview. Clicking any node opens it in the side panel and offers "expand ego graph," which re-centers the canvas on that node's neighborhood across community boundaries.

**Search.** An omnipresent command-palette-style search (Cmd+K) backed by the hybrid endpoint, with kind filters. Selecting a result jumps the canvas to that node's ego view and populates the side panel. Search is the primary entry point for anyone who knows what they're looking for; the overview is the entry point for anyone who doesn't.

**Side panel — high-value nodes and detail.** In its default state the panel shows the god-node list for the current scope: repository-wide on the overview, community-scoped after drill-in. Each entry shows name, kind, pagerank-derived importance, in/out degree, and a one-line summary; a caution glyph marks nodes whose in-degree exceeds a configurable threshold ("change carefully"). Clicking an entry focuses it on the canvas. When a node is selected the panel switches to detail mode: summary, file location with line span, metrics, grouped edge lists with confidence badges, related KB terms (vector match between the node summary and KB embeddings), and any agent-message threads anchored to the node. Edge confidence is color-coded everywhere it appears — solid for `resolved`, dashed for `llm_inferred`, dotted for `name_match` — so trust is legible at a glance in both the panel and the canvas.

## 8. Ingestion workflow and jobs

Initial ingestion is driven by Claude Code executing the ingest CLI inside the api container: register repository, tier-1 extract all files, load nodes and edges, run metrics and Leiden clustering, tier-3 summarize and embed changed nodes, tier-3 label communities, then write aggregated community edges. Incremental ingestion is triggered by a git post-commit hook (or CI step) that calls the same CLI with the changed-file list; it re-extracts hashed-changed files, repairs edges, and re-runs metrics and clustering only when the changed-edge count crosses a threshold, since community labels should stay stable across small commits. Tier 2, when enabled for a language, runs as its own job between tiers 1 and 3. Every run writes an `ingest_runs` record (add this small table when building the ingest module) with timings and node/edge deltas for the `/ingest/runs` endpoint.

## 9. Milestones

M1: compose stack up, migrations applied, tier-1 extractor for the primary language, ingest CLI loading nodes/edges. M2: metrics + clustering job, search endpoint, MCP server with `search_code`, `get_neighbors`, `impact_of`, `kb_lookup`. M3: SPA overview + drill-in + search + side panel. M4: tier-3 summaries, embeddings, community labels; hybrid search switched on. M5: agents + message board (API, MCP tools, panel threads), git-hook incrementals. M6 (optional): tier-2 LSP resolution for the language where `name_match` noise hurts most.

## 10. Open questions

Which languages need extractors on day one (determines tier-1 scope). Which embedding provider (fixes `EMBED_DIM` before the first migration — changing it later is a re-embed, not just a migration). Whether the MCP port should require a bearer token even on localhost (recommended: yes, it's one header). Whether community labeling should re-run on a schedule or only on demand (recommended: on demand; labels churning is worse than labels aging).