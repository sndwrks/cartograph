"""tool_calls

One row per MCP `tools/call`, written by `mcp_server.usage.UsageMiddleware`,
backing the usage dashboard. Byte counts are stored rather than tokens so the
chars-per-token ratio can be retuned without rewriting history:
`response_bytes` is the wire text the agent actually received, and
`baseline_bytes` is the modelled counterfactual — the size of the distinct
source files an agent would otherwise have opened (NULL when the tool has no
file counterfactual, e.g. the knowledge base and the board).

The baseline needs file sizes, which ingest never stored: `nodes.size_bytes`
is populated for `kind = 'file'` rows from here on, and the partial index
lets the per-call "sum sizes for these paths in this repository" lookup
probe (repository_id, file_path) instead of scanning every node.

Revision ID: f3a7c1e5b9d2
Revises: e8b2d4f6a1c7
Create Date: 2026-08-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f3a7c1e5b9d2"
down_revision: Union[str, None] = "e8b2d4f6a1c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.create_index(
        "ix_nodes_file_path_size",
        "nodes",
        ["repository_id", "file_path"],
        postgresql_where=sa.text("kind = 'file'"),
    )

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tool", sa.Text(), nullable=False),
        # CASCADE like every other per-repo table: SET NULL would re-label a
        # deleted repository's history as unscoped, which every surviving
        # repository's view includes
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("repo_arg", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("client_session", sa.Text(), nullable=True),
        sa.Column(
            "arguments", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("baseline_bytes", sa.BigInteger(), nullable=True),
        sa.Column("baseline_files", sa.Integer(), nullable=True),
        sa.Column("result_meta", JSONB(), nullable=True),
    )
    op.create_index("ix_tool_calls_started_at", "tool_calls", ["started_at"])
    op.create_index(
        "ix_tool_calls_repo_started", "tool_calls", ["repository_id", "started_at"]
    )
    op.create_index("ix_tool_calls_tool", "tool_calls", ["tool"])
    op.create_index("ix_tool_calls_agent_name", "tool_calls", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_agent_name", table_name="tool_calls")
    op.drop_index("ix_tool_calls_tool", table_name="tool_calls")
    op.drop_index("ix_tool_calls_repo_started", table_name="tool_calls")
    op.drop_index("ix_tool_calls_started_at", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_nodes_file_path_size", table_name="nodes")
    op.drop_column("nodes", "size_bytes")
