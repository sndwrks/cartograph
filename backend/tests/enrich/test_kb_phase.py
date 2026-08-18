"""The kb enrich phase under typed entries (slice 15)."""

from sqlalchemy import update

from cartograph.enrich import kb as kb_phase
from cartograph.models import KnowledgeEntry
from cartograph.query import kb as q_kb


def embedded_texts(fake_embedder):
    return [text for texts, _ in fake_embedder.calls for text in texts]


async def test_kb_phase_uses_type_embed_text(session, fake_embedder):
    await q_kb.create_entry(session, "PSN", "PositageNet")
    await q_kb.create_entry(
        session,
        "Flat threads",
        "Replies re-parent to the root.",
        type="decision",
        payload={"context": "Threads nested arbitrarily.", "consequences": "Two levels."},
    )
    await session.commit()

    result = await kb_phase.run(session, fake_embedder)
    assert result == {"embedded": 2, "failed": 0}

    texts = embedded_texts(fake_embedder)
    # the glossary keeps the legacy shape; the decision does not
    assert "PSN: PositageNet" in texts
    decision = next(t for t in texts if t.startswith("Flat threads"))
    assert "Threads nested arbitrarily." in decision
    assert "Two levels." in decision


async def test_kb_phase_skips_unknown_type_and_counts_failed(session, fake_embedder):
    entry = await q_kb.create_entry(session, "PSN", "PositageNet")
    await session.execute(
        update(KnowledgeEntry)
        .where(KnowledgeEntry.id == entry.id)
        .values(type="experiment")
    )
    await session.commit()

    assert await kb_phase.run(session, fake_embedder) == {"embedded": 0, "failed": 1}


async def test_kb_phase_skips_rejected_entries(session, fake_embedder):
    keep = await q_kb.create_entry(session, "PSN", "PositageNet", status="proposed")
    drop = await q_kb.create_entry(session, "DDD", "domain driven design", status="proposed")
    await q_kb.set_status(session, drop.id, "rejected", reason="not a project term")
    await session.commit()

    # proposals ARE embedded so publishing is instant; rejections never are
    assert await kb_phase.run(session, fake_embedder) == {"embedded": 1, "failed": 0}
    assert embedded_texts(fake_embedder) == [f"{keep.title}: {keep.body}"]


async def test_kb_phase_reembeds_after_payload_change(session, fake_embedder):
    entry = await q_kb.create_entry(
        session, "Flat threads", "Re-parent.", type="decision", payload={"context": "old"}
    )
    await session.commit()
    await kb_phase.run(session, fake_embedder)
    await session.refresh(entry)
    assert entry.embedding is not None

    await q_kb.update_entry(session, entry.id, {"payload": {"context": "new"}})
    await session.commit()
    await session.refresh(entry)
    assert entry.embedding is None, "a payload change must invalidate the embedding"

    fake_embedder.calls.clear()
    assert await kb_phase.run(session, fake_embedder) == {"embedded": 1, "failed": 0}
    assert "new" in embedded_texts(fake_embedder)[0]
