"""initial

Revision ID: 64f9f7a7d426
Revises: 
Create Date: 2026-08-13 16:01:55.268689

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '64f9f7a7d426'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('agents',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('role', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('knowledge_base',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('term', sa.Text(), nullable=False),
    sa.Column('definition', sa.Text(), nullable=False),
    sa.Column('aliases', sa.ARRAY(sa.Text()), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_kb_embedding_hnsw', 'knowledge_base', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_kb_term_lower', 'knowledge_base', [sa.literal_column('lower(term)')], unique=True)
    op.create_table('repositories',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('root_path', sa.Text(), nullable=False),
    sa.Column('default_branch', sa.Text(), nullable=False),
    sa.Column('last_ingested_commit', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('communities',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('node_count', sa.Integer(), nullable=False),
    sa.Column('internal_edge_count', sa.Integer(), nullable=False),
    sa.Column('algorithm', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_communities_repository_id'), 'communities', ['repository_id'], unique=False)
    op.create_table('ingest_runs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('trigger', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingest_runs_repository_id'), 'ingest_runs', ['repository_id'], unique=False)
    op.create_table('community_edges',
    sa.Column('src_community_id', sa.BigInteger(), nullable=False),
    sa.Column('dst_community_id', sa.BigInteger(), nullable=False),
    sa.Column('weight', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['dst_community_id'], ['communities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['src_community_id'], ['communities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('src_community_id', 'dst_community_id')
    )
    op.create_table('nodes',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('repository_id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.Enum('file', 'module', 'class_', 'function', 'method', 'doc', 'config', name='node_kind'), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('qualified_name', sa.Text(), nullable=False),
    sa.Column('file_path', sa.Text(), nullable=True),
    sa.Column('start_line', sa.Integer(), nullable=True),
    sa.Column('end_line', sa.Integer(), nullable=True),
    sa.Column('content_hash', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('summary_source_hash', sa.Text(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
    sa.Column('degree_in', sa.Integer(), nullable=False),
    sa.Column('degree_out', sa.Integer(), nullable=False),
    sa.Column('pagerank', sa.Float(), nullable=False),
    sa.Column('community_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['community_id'], ['communities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('repository_id', 'qualified_name', 'kind')
    )
    op.create_index(op.f('ix_nodes_community_id'), 'nodes', ['community_id'], unique=False)
    op.create_index('ix_nodes_embedding_hnsw', 'nodes', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_nodes_name_trgm', 'nodes', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_index('ix_nodes_pagerank', 'nodes', [sa.literal_column('pagerank DESC')], unique=False)
    op.create_index('ix_nodes_qname_trgm', 'nodes', ['qualified_name'], unique=False, postgresql_using='gin', postgresql_ops={'qualified_name': 'gin_trgm_ops'})
    op.create_index(op.f('ix_nodes_repository_id'), 'nodes', ['repository_id'], unique=False)
    op.create_table('agent_messages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agent_id', sa.BigInteger(), nullable=False),
    sa.Column('thread_id', sa.BigInteger(), nullable=True),
    sa.Column('subject', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('node_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['agent_messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_messages_agent_id'), 'agent_messages', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_messages_created_at'), 'agent_messages', ['created_at'], unique=False)
    op.create_index(op.f('ix_agent_messages_thread_id'), 'agent_messages', ['thread_id'], unique=False)
    op.create_table('edges',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('src_id', sa.BigInteger(), nullable=False),
    sa.Column('dst_id', sa.BigInteger(), nullable=False),
    sa.Column('rel', sa.Enum('imports', 'calls', 'inherits', 'references', 'contains', name='edge_rel'), nullable=False),
    sa.Column('confidence', sa.Enum('resolved', 'llm_inferred', 'name_match', name='edge_confidence'), nullable=False),
    sa.Column('src_line', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['dst_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['src_id'], ['nodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('src_id', 'dst_id', 'rel', 'src_line')
    )
    op.create_index(op.f('ix_edges_dst_id'), 'edges', ['dst_id'], unique=False)
    op.create_index('ix_edges_dst_rel', 'edges', ['dst_id', 'rel'], unique=False)
    op.create_index(op.f('ix_edges_src_id'), 'edges', ['src_id'], unique=False)
    op.create_index('ix_edges_src_rel', 'edges', ['src_id', 'rel'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_edges_src_rel', table_name='edges')
    op.drop_index(op.f('ix_edges_src_id'), table_name='edges')
    op.drop_index('ix_edges_dst_rel', table_name='edges')
    op.drop_index(op.f('ix_edges_dst_id'), table_name='edges')
    op.drop_table('edges')
    op.drop_index(op.f('ix_agent_messages_thread_id'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_created_at'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_agent_id'), table_name='agent_messages')
    op.drop_table('agent_messages')
    op.drop_index(op.f('ix_nodes_repository_id'), table_name='nodes')
    op.drop_index('ix_nodes_qname_trgm', table_name='nodes', postgresql_using='gin', postgresql_ops={'qualified_name': 'gin_trgm_ops'})
    op.drop_index('ix_nodes_pagerank', table_name='nodes')
    op.drop_index('ix_nodes_name_trgm', table_name='nodes', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_index('ix_nodes_embedding_hnsw', table_name='nodes', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_nodes_community_id'), table_name='nodes')
    op.drop_table('nodes')
    op.drop_table('community_edges')
    op.drop_index(op.f('ix_ingest_runs_repository_id'), table_name='ingest_runs')
    op.drop_table('ingest_runs')
    op.drop_index(op.f('ix_communities_repository_id'), table_name='communities')
    op.drop_table('communities')
    op.drop_table('repositories')
    op.drop_index('ix_kb_term_lower', table_name='knowledge_base')
    op.drop_index('ix_kb_embedding_hnsw', table_name='knowledge_base', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('knowledge_base')
    op.drop_table('agents')
    sa.Enum(name='node_kind').drop(op.get_bind())
    sa.Enum(name='edge_rel').drop(op.get_bind())
    sa.Enum(name='edge_confidence').drop(op.get_bind())
