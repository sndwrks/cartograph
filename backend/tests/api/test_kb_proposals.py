"""Propose -> review lifecycle (slice 16)."""


async def propose(client, title, body, **extra):
    r = await client.post(
        "/api/v1/kb/propose", json={"title": title, "body": body, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def publish(client, entry_id, **body):
    return await client.post(f"/api/v1/kb/{entry_id}/publish", json=body)


async def test_proposed_entry_is_invisible(client):
    """The feature. If this ever fails, nothing else about it matters."""
    entry = await propose(client, "PSN", "PositageNet")
    assert entry["status"] == "proposed"

    lookup = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    assert lookup.json() == {"match": "none", "results": []}

    listing = await client.get("/api/v1/kb")
    assert listing.json()["entries"] == []


async def test_proposals_are_listable_by_status(client):
    await propose(client, "PSN", "PositageNet")
    r = await client.get("/api/v1/kb", params={"status": "proposed"})
    body = r.json()
    assert [e["title"] for e in body["entries"]] == ["PSN"]
    assert body["total"] == 1


async def test_publish_makes_entry_visible(client):
    entry = await propose(client, "PSN", "PositageNet")
    assert (await publish(client, entry["id"])).status_code == 200

    lookup = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    body = lookup.json()
    assert body["match"] == "exact"
    assert body["results"][0]["definition"] == "PositageNet"


async def test_publish_conflicting_title_409(client):
    await client.post("/api/v1/kb", json={"title": "PSN", "body": "the incumbent"})
    challenger = await propose(client, "PSN", "a competing definition")
    # proposing was allowed — the unique index covers published rows only
    r = await publish(client, challenger["id"])
    assert r.status_code == 409


async def test_publish_with_replaces_id_archives_the_incumbent(client):
    incumbent = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "the old one"})
    ).json()
    challenger = await propose(client, "PSN", "the shorter one")

    r = await publish(client, challenger["id"], replaces_id=incumbent["id"])
    assert r.status_code == 200

    old = await client.get(f"/api/v1/kb/{incumbent['id']}")
    assert old.json()["status"] == "archived"

    lookup = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    results = lookup.json()["results"]
    assert len(results) == 1
    assert results[0]["definition"] == "the shorter one"


async def test_publish_of_published_entry_409(client):
    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    assert (await publish(client, entry["id"])).status_code == 409


async def test_archive_hides_and_republish_restores(client):
    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    assert (await client.post(f"/api/v1/kb/{entry['id']}/archive")).status_code == 200

    hidden = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    assert hidden.json() == {"match": "none", "results": []}

    assert (await publish(client, entry["id"])).status_code == 200
    back = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    assert back.json()["match"] == "exact"


async def test_reject_retains_the_row_and_its_reason(client):
    entry = await propose(client, "PSN", "PositageNet")
    r = await client.post(
        f"/api/v1/kb/{entry['id']}/reject", json={"reason": "not a project term"}
    )
    assert r.status_code == 200
    assert r.json()["review_note"] == "not a project term"

    # retained, not deleted — the reason is what reaches a future session
    kept = await client.get(f"/api/v1/kb/{entry['id']}")
    assert kept.status_code == 200
    assert kept.json()["status"] == "rejected"

    lookup = await client.get("/api/v1/kb/lookup", params={"term": "psn"})
    assert lookup.json() == {"match": "none", "results": []}


async def test_reject_requires_a_reason(client):
    entry = await propose(client, "PSN", "PositageNet")
    assert (
        await client.post(f"/api/v1/kb/{entry['id']}/reject", json={"reason": "  "})
    ).status_code == 422
    assert (
        await client.post(f"/api/v1/kb/{entry['id']}/reject", json={})
    ).status_code == 422


async def test_rejected_title_is_immediately_reusable(client):
    entry = await propose(client, "PSN", "PositageNet")
    await client.post(f"/api/v1/kb/{entry['id']}/reject", json={"reason": "no"})
    # rejected rows sit outside the partial unique indexes
    r = await client.post("/api/v1/kb", json={"title": "PSN", "body": "a good one"})
    assert r.status_code == 201


async def test_reject_of_published_entry_409(client):
    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    r = await client.post(f"/api/v1/kb/{entry['id']}/reject", json={"reason": "no"})
    assert r.status_code == 409


async def test_publishing_a_decision_assigns_its_number(client):
    entry = await propose(client, "Flat threads", "Re-parent replies.", type="decision")
    assert entry["seq"] is None
    published = await publish(client, entry["id"])
    assert published.json()["seq"] == 1


# ---- review findings 10, 12, 13 -----------------------------------------


async def test_update_scope_actually_changes_it(client, session):
    """KBUpdate used to lack `repository`, so pydantic dropped it and answered
    200 — telling the human their change had saved when it had not."""
    from cartograph.query import ingest as q_ingest

    repository = await q_ingest.upsert_repository(session, "acme", "/repos/acme")
    await session.flush()

    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    assert entry["repository_id"] is None

    r = await client.put(f"/api/v1/kb/{entry['id']}", json={"repository": "acme"})
    assert r.status_code == 200
    assert r.json()["repository_id"] == repository.id

    back = await client.put(f"/api/v1/kb/{entry['id']}", json={"repository": None})
    assert back.json()["repository_id"] is None


async def test_update_to_unknown_repository_is_422(client):
    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    r = await client.put(f"/api/v1/kb/{entry['id']}", json={"repository": "nope"})
    assert r.status_code == 422


async def test_retyping_a_published_entry_assigns_its_number(client):
    """Only set_status assigned seq, and it never runs again on a published
    row — so a retype left the entry permanently unexportable."""
    entry = (
        await client.post("/api/v1/kb", json={"title": "Flat threads", "body": "x"})
    ).json()
    assert entry["seq"] is None

    # a retype has to bring a payload the new type accepts; with that, the
    # write succeeds and the entry lands on a type that numbers its entries
    r = await client.put(
        f"/api/v1/kb/{entry['id']}",
        json={"type": "decision", "payload": {"context": "why"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["seq"] == 1
    assert r.json()["type"] == "decision"


async def test_retype_rejects_a_payload_the_new_type_cannot_hold(client):
    entry = (
        await client.post("/api/v1/kb", json={"title": "PSN", "body": "x"})
    ).json()
    # the glossary payload carries `avoid`, which Decision forbids
    r = await client.put(f"/api/v1/kb/{entry['id']}", json={"type": "decision"})
    assert r.status_code == 422


async def test_a_lost_uniqueness_race_is_409_not_500(client, session, monkeypatch):
    """_collision is an unlocked read-then-write; the loser must still get 409."""
    from cartograph.query import kb as q

    await client.post("/api/v1/kb", json={"title": "PSN", "body": "the incumbent"})

    # simulate both writers passing the pre-check, so the index is what stops
    # the second one
    monkeypatch.setattr(q, "_collision", lambda *a, **k: _none())
    r = await client.post("/api/v1/kb", json={"title": "PSN", "body": "the loser"})
    assert r.status_code == 409


async def _none():
    return None
