"""Shared test fixtures.

DB-touching tests need the dev-override Postgres reachable on 127.0.0.1:5433:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db

The suite creates and migrates a dedicated `cartograph_test` database; each test
runs inside an outer transaction that is rolled back on teardown.
"""

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cartograph.models import (
    Community,
    CommunityEdge,
    Edge,
    EdgeConfidence,
    EdgeRel,
    Node,
    NodeKind,
    Repository,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://codegraph:change-me@127.0.0.1:5433/cartograph_test",
)


async def _ensure_test_database() -> None:
    # CREATE DATABASE cannot run inside a transaction, so use raw asyncpg
    # against the admin db instead of SQLAlchemy.
    import asyncpg

    parts = urlsplit(TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    dbname = parts.path.lstrip("/")
    admin_dsn = parts._replace(path="/postgres").geturl()
    try:
        conn = await asyncpg.connect(admin_dsn)
    except OSError:
        pytest.skip(
            "test Postgres unreachable on 127.0.0.1:5433 — start it with: "
            "docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db"
        )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()


def _migrate_test_database() -> None:
    # Run alembic as a subprocess: its async env.py owns its own event loop,
    # which cannot be entered from inside a pytest-asyncio test loop.
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    await _ensure_test_database()
    _migrate_test_database()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction rolled back after each test."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        maker = async_sessionmaker(
            conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with maker() as sess:
            yield sess
        await trans.rollback()


@pytest.fixture
async def seeded(session):
    repo = Repository(name="seeded", root_path="/repos/seeded")
    session.add(repo)
    await session.flush()

    c1 = Community(repository_id=repo.id, label="core", node_count=6, internal_edge_count=4)
    c2 = Community(repository_id=repo.id, node_count=6, internal_edge_count=3)
    session.add_all([c1, c2])
    await session.flush()

    def node(kind, name, qname, pagerank, community, degree_in=0, degree_out=0):
        n = Node(
            repository_id=repo.id,
            kind=kind,
            name=name,
            qualified_name=qname,
            pagerank=pagerank,
            community_id=community.id if community else None,
            degree_in=degree_in,
            degree_out=degree_out,
        )
        session.add(n)
        return n

    order_service = node(NodeKind.class_, "OrderService", "app.services.OrderService", 0.9, c1, 1, 2)
    save = node(NodeKind.method, "save", "app.services.OrderService.save", 0.8, c1, 1, 2)
    validate = node(NodeKind.method, "validate", "app.models.Node.validate", 0.7, c1, 2, 1)
    render = node(NodeKind.function, "render", "app.models.render", 0.6, c1, 1, 1)
    base = node(NodeKind.class_, "Base", "app.models.Base", 0.5, c1, 1, 0)
    helper = node(NodeKind.function, "helper", "app.util.helper", 0.4, c1, 1, 1)
    cli = node(NodeKind.module, "cli", "app.cli", 0.35, c2, 0, 1)
    main = node(NodeKind.function, "main", "app.cli.main", 0.3, c2, 0, 2)
    util_mod = node(NodeKind.module, "util", "app.util", 0.25, c2, 1, 0)
    # equal pagerank: parse must outrank log via higher total degree
    parse = node(NodeKind.function, "parse", "app.cli.parse", 0.2, c2, 3, 1)
    log = node(NodeKind.function, "log", "app.cli.log", 0.2, c2, 1, 1)
    extra = node(NodeKind.function, "extra", "app.cli.extra", 0.1, c2)
    file_node = node(NodeKind.file, "cli.py", "app/cli.py", 0.0, None)
    await session.flush()

    def edge(src, dst, rel, confidence, line=None):
        e = Edge(
            src_id=src.id, dst_id=dst.id, rel=rel, confidence=confidence, src_line=line
        )
        session.add(e)
        return e

    edges = SimpleNamespace(
        save_validate=edge(save, validate, EdgeRel.calls, EdgeConfidence.resolved, 10),
        save_render=edge(save, render, EdgeRel.calls, EdgeConfidence.name_match, 11),
        service_base=edge(order_service, base, EdgeRel.inherits, EdgeConfidence.resolved, 5),
        main_save=edge(main, save, EdgeRel.calls, EdgeConfidence.resolved, 20),
        main_helper=edge(main, helper, EdgeRel.calls, EdgeConfidence.llm_inferred, 21),
        cli_util=edge(cli, util_mod, EdgeRel.imports, EdgeConfidence.resolved, 1),
        parse_log=edge(parse, log, EdgeRel.calls, EdgeConfidence.resolved, 30),
        log_parse=edge(log, parse, EdgeRel.calls, EdgeConfidence.resolved, 31),
        helper_validate=edge(helper, validate, EdgeRel.references, EdgeConfidence.llm_inferred, 40),
        render_parse=edge(render, parse, EdgeRel.calls, EdgeConfidence.resolved, 50),
        validate_parse=edge(validate, parse, EdgeRel.calls, EdgeConfidence.name_match, 51),
        contains_file_cli=edge(file_node, cli, EdgeRel.contains, EdgeConfidence.resolved),
        contains_cli_main=edge(cli, main, EdgeRel.contains, EdgeConfidence.resolved),
    )
    await session.flush()

    session.add_all(
        [
            CommunityEdge(src_community_id=c1.id, dst_community_id=c2.id, weight=2),
            CommunityEdge(src_community_id=c2.id, dst_community_id=c1.id, weight=2),
        ]
    )
    await session.commit()

    return SimpleNamespace(
        repo=repo,
        c1=c1,
        c2=c2,
        edges=edges,
        order_service=order_service,
        save=save,
        validate=validate,
        render=render,
        base=base,
        helper=helper,
        cli=cli,
        main=main,
        util_mod=util_mod,
        parse=parse,
        log=log,
        extra=extra,
        file_node=file_node,
    )
