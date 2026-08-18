import pytest

from cartograph.models import EMBED_DIM
from cartograph.query import kb as q_kb
from cartograph.query import search as q_search
from fakes import FakeEmbedder


def unit_vector(axis: int) -> list[float]:
    vector = [0.0] * EMBED_DIM
    vector[axis] = 1.0
    return vector


@pytest.fixture
async def embedded_seeded(session, seeded):
    # save ~ axis 0, helper ~ axis 1
    seeded.save.embedding = unit_vector(0)
    seeded.save.summary = "Persists an order."
    seeded.helper.embedding = unit_vector(1)
    seeded.helper.summary = "Doubles a value."
    await session.commit()
    return seeded


async def test_semantic_search_orders_by_cosine(session, embedded_seeded):
    embedder = FakeEmbedder(overrides={"persist orders": unit_vector(0)})
    results = await q_search.search_semantic(
        session, "seeded", "persist orders", limit=5, embedder=embedder
    )
    assert results[0].node.qualified_name == "app.services.OrderService.save"
    assert results[0].score == pytest.approx(1.0)
    assert results[0].source == "semantic"
    assert embedder.calls[0][1] == "query"


async def test_hybrid_merges_with_rrf(session, embedded_seeded):
    # text ranks helper first (name match); semantic ranks save first
    embedder = FakeEmbedder(overrides={"help": unit_vector(0)})
    results, degraded = await q_search.search_hybrid(
        session, "seeded", "help", limit=5, embedder=embedder
    )
    assert degraded is False
    names = [result.node.qualified_name for result in results]
    # helper appears in both rankings, so RRF puts it first
    assert names[0] == "app.util.helper"
    assert "app.services.OrderService.save" in names
    assert all(result.source == "hybrid" for result in results)


async def test_search_router_modes(session, client, embedded_seeded, monkeypatch):
    fake = FakeEmbedder(overrides={"persist orders": unit_vector(0)})
    monkeypatch.setattr(q_search, "get_default_embedder", lambda: fake)

    semantic = await client.get(
        "/api/v1/search",
        params={"q": "persist orders", "repo": "seeded", "mode": "semantic"},
    )
    assert semantic.status_code == 200  # 501 removed
    assert semantic.json()["results"][0]["node"]["name"] == "save"

    hybrid = await client.get(
        "/api/v1/search", params={"q": "persist orders", "repo": "seeded"}
    )
    assert hybrid.status_code == 200
    assert "degraded" not in hybrid.json()


async def test_hybrid_degrades_without_embedder(session, seeded, monkeypatch):
    monkeypatch.setattr(q_search, "get_default_embedder", lambda: None)
    results, degraded = await q_search.search_hybrid(session, "seeded", "helper")
    assert degraded is True
    assert results


async def test_kb_vector_fallback(session):
    psn = await q_kb.create_entry(session, "PSN", "PositageNet")
    other = await q_kb.create_entry(session, "DDD", "domain driven design")
    psn.embedding = unit_vector(0)
    other.embedding = unit_vector(1)
    await session.flush()

    embedder = FakeEmbedder(overrides={"positage network": unit_vector(0)})
    result = await q_kb.lookup(session, "positage network", embedder=embedder)
    assert result["match"] == "vector"
    assert result["results"][0].term == "PSN"

    # determinism guarantee: exact match never consults the embedder
    exact = await q_kb.lookup(session, "psn", embedder=embedder)
    assert exact["match"] == "exact"
    assert len(embedder.calls) == 1


async def test_related_kb_endpoint(session, client, embedded_seeded):
    psn = await q_kb.create_entry(session, "PSN", "PositageNet")
    other = await q_kb.create_entry(session, "DDD", "domain driven design")
    psn.embedding = unit_vector(0)  # nearest to seeded.save
    other.embedding = unit_vector(1)
    await session.commit()

    response = await client.get(f"/api/v1/nodes/{embedded_seeded.save.id}/related-kb")
    assert response.status_code == 200
    terms = response.json()["terms"]
    assert terms[0]["term"] == "PSN"
    assert terms[0]["score"] == pytest.approx(1.0)

    # unembedded node -> empty list, not an error
    bare = await client.get(f"/api/v1/nodes/{embedded_seeded.extra.id}/related-kb")
    assert bare.status_code == 200
    assert bare.json()["terms"] == []
