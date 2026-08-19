import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cartograph.models import (
    EMBED_DIM,
    Agent,
    AgentMessage,
    Community,
    CommunityEdge,
    Edge,
    EdgeConfidence,
    EdgeRel,
    IngestRun,
    KnowledgeEntry,
    Node,
    NodeKind,
    Repository,
)


async def _make_repo(session: AsyncSession) -> Repository:
    repo = Repository(name="test-repo", root_path="/repos/test")
    session.add(repo)
    await session.flush()
    return repo


async def test_repository_roundtrip(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    got = await session.get(Repository, repo.id)
    assert got is not None
    assert got.name == "test-repo"
    assert got.default_branch == "main"
    assert isinstance(got.created_at, datetime.datetime)


async def test_node_roundtrip_with_embedding(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    node = Node(
        repository_id=repo.id,
        kind=NodeKind.class_,
        name="OrderService",
        qualified_name="pkg.services.OrderService",
        file_path="pkg/services.py",
        start_line=10,
        end_line=42,
        content_hash="abc123",
        embedding=[0.1] * EMBED_DIM,
    )
    session.add(node)
    await session.flush()
    got = await session.get(Node, node.id)
    assert got is not None
    assert got.kind is NodeKind.class_
    assert got.pagerank == 0.0
    assert got.embedding is not None and len(got.embedding) == EMBED_DIM


async def test_edge_roundtrip(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    src = Node(repository_id=repo.id, kind=NodeKind.function,
               name="caller", qualified_name="pkg.a.caller")
    dst = Node(repository_id=repo.id, kind=NodeKind.function,
               name="callee", qualified_name="pkg.b.callee")
    session.add_all([src, dst])
    await session.flush()
    edge = Edge(src_id=src.id, dst_id=dst.id, rel=EdgeRel.calls,
                confidence=EdgeConfidence.resolved, src_line=7)
    session.add(edge)
    await session.flush()
    got = (await session.execute(select(Edge).where(Edge.src_id == src.id))).scalar_one()
    assert got.rel is EdgeRel.calls
    assert got.confidence is EdgeConfidence.resolved


async def test_community_and_community_edge_roundtrip(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    c1 = Community(repository_id=repo.id, label="Payments", node_count=3)
    c2 = Community(repository_id=repo.id, label="Auth", node_count=2)
    session.add_all([c1, c2])
    await session.flush()
    ce = CommunityEdge(src_community_id=c1.id, dst_community_id=c2.id, weight=5)
    session.add(ce)
    await session.flush()
    got = await session.get(CommunityEdge, (c1.id, c2.id))
    assert got is not None and got.weight == 5
    assert c1.algorithm == "leiden"


async def test_node_community_fk(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    community = Community(repository_id=repo.id)
    session.add(community)
    await session.flush()
    node = Node(repository_id=repo.id, kind=NodeKind.module,
                name="pkg", qualified_name="pkg", community_id=community.id)
    session.add(node)
    await session.flush()
    got = await session.get(Node, node.id)
    assert got is not None and got.community_id == community.id


async def test_agent_and_message_roundtrip(session: AsyncSession) -> None:
    agent = Agent(name="claude-worker", role="reviewer",
                  metadata_json={"model": "claude-fable-5", "k": [1, 2]})
    session.add(agent)
    await session.flush()
    root = AgentMessage(agent_id=agent.id, subject="hello", body="root message")
    session.add(root)
    await session.flush()
    reply = AgentMessage(agent_id=agent.id, thread_id=root.id, body="a reply")
    session.add(reply)
    await session.flush()
    got_agent = await session.get(Agent, agent.id)
    assert got_agent is not None
    assert got_agent.metadata_json == {"model": "claude-fable-5", "k": [1, 2]}
    assert got_agent.status == "idle"
    got_reply = await session.get(AgentMessage, reply.id)
    assert got_reply is not None and got_reply.thread_id == root.id


async def test_knowledge_entry_roundtrip(session: AsyncSession) -> None:
    entry = KnowledgeEntry(
        type="glossary",
        slug="psn",
        title="PSN",
        body="PositageNet — never any other expansion",
        aliases=["positage", "positagenet"],
        category="acronym",
        embedding=[0.2] * EMBED_DIM,
    )
    session.add(entry)
    await session.flush()
    got = (await session.execute(
        select(KnowledgeEntry).where(KnowledgeEntry.title == "PSN")
    )).scalar_one()
    assert got.aliases == ["positage", "positagenet"]
    assert got.embedding is not None and len(got.embedding) == EMBED_DIM


async def test_knowledge_entry_defaults(session: AsyncSession) -> None:
    entry = KnowledgeEntry(type="glossary", slug="ddd", title="DDD", body="…")
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    assert entry.payload == {}
    assert entry.status == "published"
    assert entry.created_at is not None
    assert entry.seq is None and entry.repository_id is None


async def test_ingest_run_roundtrip(session: AsyncSession) -> None:
    repo = await _make_repo(session)
    run = IngestRun(repository_id=repo.id,
                    stats={"files_changed": 3, "timings": {"walk": 0.01}})
    session.add(run)
    await session.flush()
    got = await session.get(IngestRun, run.id)
    assert got is not None
    assert got.trigger == "manual"
    assert got.status == "running"
    assert got.stats == {"files_changed": 3, "timings": {"walk": 0.01}}
