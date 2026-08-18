from pathlib import Path

import pytest

from cartograph.ingest.loader import ingest_repo
from cartograph.query import ingest as qi

FIXTURE = Path(__file__).parents[1] / "extractors" / "fixtures" / "py_sample"


@pytest.fixture
async def ingested(session):
    repo = await qi.upsert_repository(session, "py_sample", str(FIXTURE))
    await session.commit()
    await ingest_repo(session, repo)
    return repo


async def test_list_runs(client, ingested):
    r = await client.get("/api/v1/ingest/runs", params={"repo": "py_sample"})
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert run["repository"] == "py_sample"
    assert run["status"] == "succeeded"
    assert run["stats"]["files_changed"] == 6
    assert run["finished_at"] is not None
    assert run["error"] is None  # list view omits error detail


async def test_list_runs_unknown_repo(client, ingested):
    assert (
        await client.get("/api/v1/ingest/runs", params={"repo": "nope"})
    ).status_code == 404


async def test_run_detail_includes_error(client, session, ingested):
    ingested.root_path = str(FIXTURE / "missing")
    await session.commit()
    with pytest.raises(FileNotFoundError):
        await ingest_repo(session, ingested)

    r = await client.get("/api/v1/ingest/runs", params={"repo": "py_sample"})
    runs = r.json()["runs"]
    assert len(runs) == 2
    assert runs[0]["status"] == "failed"  # newest first

    detail = await client.get(f"/api/v1/ingest/runs/{runs[0]['id']}")
    assert detail.status_code == 200
    assert "FileNotFoundError" in detail.json()["error"]

    assert (await client.get("/api/v1/ingest/runs/999999")).status_code == 404
