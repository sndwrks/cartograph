"""repo_uuid

A stable public identifier for repositories. The SPA puts the selected
repository in the URL (`/repo/<uuid>/...`); the autoincrement `id` would work
but leaks insertion order, and the `name` breaks every bookmark on a rename.
`gen_random_uuid()` is built into PostgreSQL 13+, so NOT NULL plus a server
default backfills existing rows in the same statement.

Revision ID: e8b2d4f6a1c7
Revises: d7a1c5e9f3b2
Create Date: 2026-08-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "e8b2d4f6a1c7"
down_revision: Union[str, None] = "d7a1c5e9f3b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column(
            "uuid",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_index("ix_repositories_uuid", "repositories", ["uuid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_repositories_uuid", table_name="repositories")
    op.drop_column("repositories", "uuid")
