"""enrich_batches

Resume state for the Anthropic Message Batches enrichment mode
(`python -m cartograph.enrich --batch / --batch-status / --batch-collect`).
One row per provider batch; submit → ended → collected.

Revision ID: d7a1c5e9f3b2
Revises: c4d8e2f7a1b3
Create Date: 2026-08-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d7a1c5e9f3b2"
down_revision: Union[str, None] = "c4d8e2f7a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enrich_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("provider_batch_id", sa.Text(), nullable=True, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("node_id_min", sa.BigInteger(), nullable=True),
        sa.Column("node_id_max", sa.BigInteger(), nullable=True),
        sa.Column("counts", JSONB(), nullable=True),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_enrich_batches_repository_id", "enrich_batches", ["repository_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_enrich_batches_repository_id", table_name="enrich_batches")
    op.drop_table("enrich_batches")
