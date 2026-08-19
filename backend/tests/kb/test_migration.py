"""The typed-KB migration, exercised end to end.

These tests run `alembic downgrade`/`upgrade`, which mutates schema — they
therefore cannot use the shared session-scoped engine and its per-test outer
transaction (tests/conftest.py). They get their own throwaway database on the
same raw-asyncpg pattern as `_ensure_test_database`.

Every test starts from the pre-typed schema with an empty table and seeds what
it needs, so any one of them can be run alone — which is exactly what you do
when bisecting a migration failure.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text

from cartograph.kb.slug import FALLBACK, slugify
from test_slug import SHARED_CASES

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://codegraph:change-me@127.0.0.1:5433/cartograph_test",
)
MIGRATION_DB = "cartograph_migration_test"
INITIAL_REVISION = "64f9f7a7d426"

# The migration's slug expression, character for character.
SLUG_SQL = (
    "nullif(trim(both '-' from "
    "regexp_replace(lower(:value), '[^a-z0-9]+', '-', 'g')), '')"
)


def _dsn(dbname: str) -> str:
    parts = urlsplit(BASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    return parts._replace(path=f"/{dbname}").geturl()


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url.replace(
            "postgresql://", "postgresql+asyncpg://"
        )},
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AssertionError(f"alembic {' '.join(args)} failed:\n{result.stderr}")


@pytest.fixture(scope="module")
async def migration_db():
    import asyncpg

    admin = _dsn("postgres")
    try:
        conn = await asyncpg.connect(admin)
    except OSError:
        if os.environ.get("CI"):
            # See tests/conftest.py: in CI an unreachable database is a failure,
            # never a skip.
            raise
        pytest.skip(
            "test Postgres unreachable on 127.0.0.1:5433 — start it with: "
            "docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db"
        )
    await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{MIGRATION_DB}"')
    await conn.close()

    yield _dsn(MIGRATION_DB)

    conn = await asyncpg.connect(admin)
    await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
    await conn.close()


@pytest.fixture
async def at_initial(migration_db):
    """Pre-typed schema, empty table. Independent of test order."""
    import asyncpg

    _alembic(migration_db, "downgrade", "base")
    _alembic(migration_db, "upgrade", INITIAL_REVISION)
    conn = await asyncpg.connect(migration_db)
    await conn.execute("TRUNCATE knowledge_base RESTART IDENTITY CASCADE")
    await conn.close()
    return migration_db


async def seed_legacy(dsn: str, rows: list[tuple[str, str]]) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    await conn.executemany(
        "INSERT INTO knowledge_base (term, definition, updated_at) "
        "VALUES ($1, $2, now())",
        rows,
    )
    await conn.close()


async def fetch(dsn: str, sql: str) -> list:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


async def execute(dsn: str, sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def test_legacy_rows_backfill_to_published_glossary(at_initial):
    await seed_legacy(
        at_initial,
        [("PSN", "PositageNet"), ("DDD", "domain driven design")],
    )
    _alembic(at_initial, "upgrade", "head")

    rows = await fetch(
        at_initial,
        "SELECT type, slug, title, body, status, source, payload, repository_id, "
        "seq, created_at, updated_at FROM knowledge_base ORDER BY id",
    )
    assert [r["title"] for r in rows] == ["PSN", "DDD"]
    assert [r["body"] for r in rows] == ["PositageNet", "domain driven design"]
    assert {r["type"] for r in rows} == {"glossary"}
    assert {r["status"] for r in rows} == {"published"}
    assert {r["source"] for r in rows} == {"legacy"}
    assert {r["payload"] for r in rows} == {"{}"}
    # every legacy entry is global and unnumbered
    assert {r["repository_id"] for r in rows} == {None}
    assert {r["seq"] for r in rows} == {None}
    assert all(r["created_at"] == r["updated_at"] for r in rows)
    assert [r["slug"] for r in rows] == ["psn", "ddd"]


async def test_slug_dedupe_survives_a_suffix_that_is_itself_taken(at_initial):
    """The case a row_number() suffix gets wrong.

    'PS-N', 'PS N' and 'PS N 2' are all distinct under the old unique
    lower(term) index but slugify to ps-n, ps-n, ps-n-2 — so suffixing the
    second with its row number produces 'ps-n-2', which the third already owns,
    and step 7's unique index aborts the upgrade on a live table.
    """
    await seed_legacy(
        at_initial,
        [("PS-N", "hyphen"), ("PS N", "space"), ("PS N 2", "space two"), ("!!!", "punct")],
    )
    _alembic(at_initial, "upgrade", "head")  # must not raise

    rows = await fetch(
        at_initial, "SELECT id, title, slug FROM knowledge_base ORDER BY id"
    )
    slugs = [r["slug"] for r in rows]
    assert len(set(slugs)) == len(slugs), slugs
    assert slugs[0] == "ps-n"
    assert slugs[2] == "ps-n-2"  # the row that legitimately owns it keeps it
    # the loser gets a double-hyphen suffix, which no slugified term can spell
    assert slugs[1] == f"ps-n--{rows[1]['id']}"
    assert slugs[3] == f"entry-{rows[3]['id']}"  # punctuation-only slugifies away


def test_double_hyphen_is_unreachable_by_slugify():
    """What makes the dedupe suffix collision-proof."""
    for value, _ in SHARED_CASES:
        assert "--" not in slugify(value)
    assert "--" not in slugify("a -- b")
    assert "--" not in slugify("PS   N")


async def test_upgrade_drops_the_old_shape(at_initial):
    await seed_legacy(at_initial, [("PSN", "PositageNet")])
    _alembic(at_initial, "upgrade", "head")

    columns = {
        r["column_name"]
        for r in await fetch(
            at_initial,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'knowledge_base'",
        )
    }
    indexes = {
        r["indexname"]
        for r in await fetch(
            at_initial,
            "SELECT indexname FROM pg_indexes WHERE tablename = 'knowledge_base'",
        )
    }
    assert "term" not in columns and "definition" not in columns
    assert "ix_kb_term_lower" not in indexes
    assert {"ix_kb_ident", "ix_kb_title_lower", "ix_kb_seq"} <= indexes
    # embeddings survive the migration, so nothing has to be re-paid at Voyage
    assert "ix_kb_embedding_hnsw" in indexes


async def test_downgrade_drops_everything_the_old_schema_cannot_hold(at_initial):
    """Not merely lossy — keeping these rows would CORRUPT.

    A rejected glossary entry that survived would lose its status and
    review_note and come back as a live term, turning a definition a human
    explicitly refused into fact.
    """
    await seed_legacy(at_initial, [("PSN", "PositageNet")])
    _alembic(at_initial, "upgrade", "head")
    await execute(
        at_initial,
        """
        INSERT INTO knowledge_base (type, slug, title, body, status, payload, review_note)
        VALUES ('runbook', 'rotate', 'Rotate key', 'Steps.', 'published', '{}', NULL),
               ('glossary', 'psn-2', 'PSN', 'Payment Service Node', 'rejected', '{}',
                'wrong — PSN is PositageNet'),
               ('glossary', 'ddd', 'DDD', 'a proposal', 'proposed', '{}', NULL)
        """,
    )

    _alembic(at_initial, "downgrade", INITIAL_REVISION)

    rows = await fetch(
        at_initial, "SELECT term, definition FROM knowledge_base ORDER BY id"
    )
    assert [r["term"] for r in rows] == ["PSN"]
    assert rows[0]["definition"] == "PositageNet"
    indexes = {
        r["indexname"]
        for r in await fetch(
            at_initial,
            "SELECT indexname FROM pg_indexes WHERE tablename = 'knowledge_base'",
        )
    }
    assert "ix_kb_term_lower" in indexes


async def test_downgrade_survives_a_published_entry_and_its_proposed_revision(
    at_initial,
):
    """ix_kb_term_lower is NOT partial, so both rows cannot coexist under it.

    The typed schema allows them (ix_kb_title_lower is WHERE status='published')
    and the documented revision flow creates them, so a downgrade that kept the
    proposal would abort halfway through.
    """
    await seed_legacy(at_initial, [("PSN", "PositageNet")])
    _alembic(at_initial, "upgrade", "head")
    await execute(
        at_initial,
        "INSERT INTO knowledge_base (type, slug, title, body, status, payload) "
        "VALUES ('glossary', 'psn-rev', 'PSN', 'a shorter one', 'proposed', '{}')",
    )

    _alembic(at_initial, "downgrade", INITIAL_REVISION)  # must not raise

    rows = await fetch(at_initial, "SELECT term FROM knowledge_base")
    assert [r["term"] for r in rows] == ["PSN"]


async def test_slugify_matches_migration_regex(session):
    """The Python and SQL implementations must not drift.

    Uses the ordinary session — it only evaluates an expression and touches no
    schema, so it needs neither the throwaway database nor alembic.
    """
    for value, _ in SHARED_CASES:
        sql_slug = await session.scalar(text(f"SELECT {SLUG_SQL}"), {"value": value})
        # NULL is where the migration falls back to 'entry-<id>' and slugify
        # falls back to 'entry'; both agree that the regex produced nothing.
        assert (sql_slug or FALLBACK) == slugify(value), value
