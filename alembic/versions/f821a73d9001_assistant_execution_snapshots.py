"""Add opt-in, owned assistant snapshots; no changes to existing simulation logs."""
from alembic import op
import sqlalchemy as sa

revision = 'f821a73d9001'
down_revision = 'e7a124b891c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('assistant_executions',
        sa.Column('execution_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(50), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('artifact_sha256', sa.String(64), nullable=False),
        sa.Column('result_version', sa.String(64), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False))
    op.create_index('ix_assistant_execution_owner_created', 'assistant_executions', ['user_id', 'created_at'])
    op.create_index('ix_assistant_execution_expires', 'assistant_executions', ['expires_at'])


def downgrade():
    op.drop_table('assistant_executions')
