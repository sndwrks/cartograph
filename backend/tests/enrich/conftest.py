"""Enrichment test fixtures: fake LLM/embedding clients — no real API calls."""

import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cartograph.api.app import create_app
from cartograph.db import get_session
from cartograph.ingest.loader import ingest_repo
from cartograph.metrics.job import run_metrics
from cartograph.query import ingest as qi
from fakes import FakeEmbedder, FakeLLM

FIXTURE = Path(__file__).parents[1] / "extractors" / "fixtures" / "py_sample"

README = """# py_sample

A tiny fixture package. The `helper` function in pkg.util.helper doubles
values, and OrderService persists orders via pkg.models.Node.
"""


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def repo_root(tmp_path):
    root = tmp_path / "py_sample"
    shutil.copytree(FIXTURE, root)
    (root / "README.md").write_text(README)
    return root


@pytest.fixture
async def repo(session, repo_root):
    repo = await qi.upsert_repository(session, "py_sample", str(repo_root))
    await session.commit()
    await ingest_repo(session, repo)
    await run_metrics(session, repo)
    return repo


@pytest.fixture
async def client(session):
    app = create_app()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
