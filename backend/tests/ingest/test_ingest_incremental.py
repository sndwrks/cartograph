import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import aliased

from cartograph.ingest.loader import ingest_repo
from cartograph.models import Edge, IngestRun, Node, NodeKind
from cartograph.query import ingest as q

FIXTURE = Path(__file__).parents[1] / "extractors" / "fixtures" / "py_sample"

ALL_PATHS = {
    "pkg/__init__.py",
    "pkg/broken.py",
    "pkg/cli.py",
    "pkg/models.py",
    "pkg/services.py",
    "pkg/util.py",
}


@pytest.fixture
def repo_root(tmp_path):
    root = tmp_path / "py_sample"
    shutil.copytree(FIXTURE, root)
    return root


async def register(session, root):
    repo = await q.upsert_repository(session, "py_sample", str(root))
    await session.commit()
    return repo


async def node_ids(session, repo_id) -> dict[tuple[str, str], int]:
    rows = await session.execute(
        select(Node.qualified_name, Node.kind, Node.id).where(
            Node.repository_id == repo_id
        )
    )
    return {(qname, kind.value): node_id for qname, kind, node_id in rows.all()}


async def edge_set(session, repo_id) -> set[tuple[str, str, str, str]]:
    src, dst = aliased(Node), aliased(Node)
    rows = await session.execute(
        select(src.qualified_name, dst.qualified_name, Edge.rel, Edge.confidence)
        .select_from(Edge)
        .join(src, Edge.src_id == src.id)
        .join(dst, Edge.dst_id == dst.id)
        .where(src.repository_id == repo_id)
    )
    return {(s, d, rel.value, conf.value) for s, d, rel, conf in rows.all()}


async def test_full_ingest(session, repo_root):
    repo = await register(session, repo_root)
    stats = await ingest_repo(session, repo, trigger="manual")

    assert stats["files_seen"] == 6
    assert stats["files_changed"] == 6
    assert stats["nodes_added"] > 0

    ids = await node_ids(session, repo.id)
    assert {q for (q, k) in ids if k == "file"} == ALL_PATHS

    node = await session.scalar(
        select(Node).where(
            Node.repository_id == repo.id,
            Node.qualified_name == "pkg.models.Node",
            Node.kind == NodeKind.class_,
        )
    )
    assert node is not None
    assert (node.start_line, node.end_line) == (6, 8)
    assert node.file_path == "pkg/models.py"

    edges = await edge_set(session, repo.id)
    for expected in [
        ("pkg/models.py", "pkg.models", "contains", "resolved"),
        ("pkg.models", "pkg.models.Node", "contains", "resolved"),
        ("pkg.models.Node", "pkg.models.Node.validate", "contains", "resolved"),
        ("pkg.services.OrderService.save", "pkg.models.Node", "calls", "resolved"),
        ("pkg.models.Node", "pkg.models.Base", "inherits", "resolved"),
        ("pkg.cli", "pkg.services.OrderService", "imports", "resolved"),
        ("pkg.cli", "pkg.util", "imports", "resolved"),
        ("pkg.cli.main", "pkg.util.helper", "calls", "resolved"),
        ("pkg.cli", "pkg.util.helper", "references", "resolved"),
        (
            "pkg.services.OrderService.save",
            "pkg.services.OrderService.check",
            "calls",
            "resolved",
        ),
        ("pkg.services.OrderService.save", "pkg.models.render", "calls", "name_match"),
        ("pkg.services.OrderService.save", "pkg.util.render", "calls", "name_match"),
    ]:
        assert expected in edges, expected

    run = await session.scalar(
        select(IngestRun)
        .where(IngestRun.repository_id == repo.id)
        .order_by(IngestRun.id.desc())
    )
    assert run.status == "succeeded"
    assert run.finished_at is not None
    assert run.stats and run.stats["files_changed"] == 6


async def test_noop_rerun(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    before = await node_ids(session, repo.id)

    stats = await ingest_repo(session, repo)
    assert stats["files_changed"] == 0
    assert stats["files_dependent"] == 0
    assert stats["nodes_added"] == 0
    assert stats["nodes_deleted"] == 0
    assert stats["edges_added"] == 0
    assert stats["edges_deleted"] == 0
    assert await node_ids(session, repo.id) == before


async def test_incremental_change_with_dependent_expansion(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    before = await node_ids(session, repo.id)

    util = repo_root / "pkg" / "util.py"
    util.write_text(
        util.read_text()
        + "\n\ndef extra():\n    from pkg.models import Base\n    return Base()\n"
    )
    stats = await ingest_repo(session, repo)
    assert stats["files_changed"] == 1
    # cli.py and services.py both have edges into pkg.util nodes
    assert stats["files_dependent"] >= 1

    after = await node_ids(session, repo.id)
    for key, node_id in before.items():
        qname = key[0]
        if not (qname.startswith("pkg.util") or qname == "pkg/util.py"):
            assert after[key] == node_id, key
    assert ("pkg.util.extra", "function") in after

    edges = await edge_set(session, repo.id)
    assert ("pkg.util.extra", "pkg.models.Base", "calls", "resolved") in edges
    # an edge INTO the changed file from an unchanged file survives the re-run
    assert ("pkg.cli.main", "pkg.util.helper", "calls", "resolved") in edges
    assert ("pkg.cli", "pkg.util", "imports", "resolved") in edges


async def test_full_flag_rewrites_everything(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    before = await node_ids(session, repo.id)
    stats = await ingest_repo(session, repo, full=True)
    assert stats["files_changed"] == 6
    # upsert-then-prune: unchanged content keeps every node id (and with it
    # any summary/embedding), nothing is deleted, and nodes_added reports
    # genuine inserts rather than conflicted updates
    assert stats["nodes_deleted"] == 0
    assert stats["nodes_added"] == 0
    assert await node_ids(session, repo.id) == before


async def test_reingest_preserves_summaries(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    helper = await session.scalar(
        select(Node).where(
            Node.repository_id == repo.id,
            Node.qualified_name == "pkg.util.helper",
        )
    )
    helper.summary = "adds one"
    helper.summary_source_hash = helper.content_hash
    await session.commit()
    helper_id = helper.id

    await ingest_repo(session, repo, full=True)
    helper = await session.scalar(
        select(Node).where(
            Node.repository_id == repo.id,
            Node.qualified_name == "pkg.util.helper",
        )
    )
    assert helper.id == helper_id
    assert helper.summary == "adds one"


async def test_removed_symbol_pruned(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    assert ("pkg.util.render", "function") in await node_ids(session, repo.id)

    util = repo_root / "pkg" / "util.py"
    util.write_text(
        "\n".join(
            line
            for line in util.read_text().splitlines()
            if not line.startswith("def render")
            and not line.startswith('    return "util"')
        )
        + "\n"
    )
    stats = await ingest_repo(session, repo)
    assert stats["nodes_deleted"] > 0
    assert ("pkg.util.render", "function") not in await node_ids(session, repo.id)


async def test_deletion(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    edges_before = await edge_set(session, repo.id)
    assert any(s.startswith("pkg.cli") for s, *_ in edges_before)

    (repo_root / "pkg" / "cli.py").unlink()
    stats = await ingest_repo(session, repo)
    assert stats["nodes_deleted"] > 0

    ids = await node_ids(session, repo.id)
    assert not [key for key in ids if key[0].startswith("pkg.cli") or key[0] == "pkg/cli.py"]
    edges = await edge_set(session, repo.id)
    dangling = [
        e
        for e in edges
        if e[0].startswith("pkg.cli")
        or e[1].startswith("pkg.cli")
        or e[0] == "pkg/cli.py"
    ]
    assert dangling == []


async def test_files_restriction(session, repo_root):
    repo = await register(session, repo_root)
    await ingest_repo(session, repo)

    util = repo_root / "pkg" / "util.py"
    util.write_text(util.read_text() + "\n\ndef another():\n    return 3\n")
    models = repo_root / "pkg" / "models.py"
    models.write_text(models.read_text() + "\n\ndef also_new():\n    return 4\n")

    stats = await ingest_repo(session, repo, files=["pkg/util.py"])
    assert stats["files_seen"] == 1
    assert stats["files_changed"] == 1
    ids = await node_ids(session, repo.id)
    assert ("pkg.util.another", "function") in ids
    # models.py was changed on disk but not listed, so it was not touched
    assert ("pkg.models.also_new", "function") not in ids


async def test_failed_run_recorded(session, repo_root):
    repo = await register(session, repo_root)
    repo.root_path = str(repo_root / "does-not-exist")
    await session.commit()

    with pytest.raises(FileNotFoundError):
        await ingest_repo(session, repo)

    run = await session.scalar(
        select(IngestRun)
        .where(IngestRun.repository_id == repo.id)
        .order_by(IngestRun.id.desc())
    )
    assert run.status == "failed"
    assert run.error and "FileNotFoundError" in run.error


async def test_exclude_dirs(session, repo_root):
    gen = repo_root / "generated"
    gen.mkdir()
    (gen / "bundle.py").write_text("def blob():\n    return 1\n")

    repo = await register(session, repo_root)
    await ingest_repo(session, repo)
    ids = await node_ids(session, repo.id)
    assert ("generated/bundle.py", "file") in ids

    # excluding after the fact removes the stale nodes on the next full walk
    repo = await q.upsert_repository(
        session, "py_sample", str(repo_root), exclude_dirs=["generated"]
    )
    await session.commit()
    stats = await ingest_repo(session, repo)
    assert stats["nodes_deleted"] >= 1
    ids = await node_ids(session, repo.id)
    assert not any(qname.startswith("generated") for (qname, _kind) in ids)
    assert ("pkg/util.py", "file") in ids

    # the --files path (hook freshenings) can't sneak an excluded file back in
    stats = await ingest_repo(session, repo, files=["generated/bundle.py"])
    assert stats["files_seen"] == 0
    ids = await node_ids(session, repo.id)
    assert not any(qname.startswith("generated") for (qname, _kind) in ids)


async def test_exclude_dirs_kept_when_flag_omitted(session, repo_root):
    await q.upsert_repository(
        session, "py_sample", str(repo_root), exclude_dirs=["generated"]
    )
    await session.commit()

    # re-register without exclude_dirs (the CLI passes None) keeps the list
    repo = await q.upsert_repository(session, "py_sample", str(repo_root))
    await session.commit()
    assert repo.exclude_dirs == ["generated"]

    # an explicit empty list clears it
    repo = await q.upsert_repository(
        session, "py_sample", str(repo_root), exclude_dirs=[]
    )
    await session.commit()
    assert repo.exclude_dirs == []


async def test_upsert_nodes_dedupes_within_batch(session, repo_root):
    # minified bundles carry duplicate qualified names in one file; Postgres
    # rejects ON CONFLICT DO UPDATE hitting the same row twice per statement
    repo = await register(session, repo_root)
    row = {
        "repository_id": repo.id,
        "kind": NodeKind.function,
        "name": "To",
        "qualified_name": "bundle.To",
        "file_path": "bundle.js",
        "start_line": 1,
        "end_line": 1,
        "content_hash": "first",
    }
    ids, inserted = await q.upsert_nodes(
        session, [row, {**row, "content_hash": "last"}]
    )
    assert list(ids) == ["bundle.To"]
    assert inserted == 1
    node = await session.get(Node, ids["bundle.To"])
    assert node.content_hash == "last"
