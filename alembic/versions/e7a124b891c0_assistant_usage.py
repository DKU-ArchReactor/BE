"""Persistent assistant request allowance across workers and restarts."""
from alembic import op
import sqlalchemy as sa

revision = 'e7a124b891c0'
down_revision = '5e62e48b1f36'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'assistant_usage',
        sa.Column('user_id', sa.String(50), primary_key=True),
        sa.Column('usage_date', sa.Date(), primary_key=True),
        sa.Column('request_count', sa.Integer(), nullable=False),
        sa.Column('last_requested_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('assistant_usage')
