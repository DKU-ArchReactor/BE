"""Preserve separate compiler streams; old builds keep their combined log."""
from alembic import op
import sqlalchemy as sa
revision = 'f281a64b209e'
down_revision = 'f821a73d9001'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('builds', sa.Column('stdout', sa.Text(), nullable=True))
    op.add_column('builds', sa.Column('stderr', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('builds', 'stderr')
    op.drop_column('builds', 'stdout')
