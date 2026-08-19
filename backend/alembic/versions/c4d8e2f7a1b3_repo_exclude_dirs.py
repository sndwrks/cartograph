"""repo exclude_dirs

Per-repository directory exclusions for ingest and docs discovery, set via
`ingest register --exclude`. Basename semantics, same as the built-in
deny-list in cartograph.ingest.walker.

Revision ID: c4d8e2f7a1b3
Revises: b7e3c1a4d92f
Create Date: 2026-08-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2f7a1b3"
down_revision: Union[str, None] = "b7e3c1a4d92f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column(
            "exclude_dirs",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("repositories", "exclude_dirs")
