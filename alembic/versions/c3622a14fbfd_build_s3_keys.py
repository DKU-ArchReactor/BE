"""build s3 keys

Revision ID: c3622a14fbfd
Revises: 995335956c96
Create Date: 2026-05-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3622a14fbfd'
down_revision: Union[str, None] = '995335956c96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('builds', sa.Column('binary_key', sa.String(length=512), nullable=True))
    op.add_column('builds', sa.Column('assembly_key', sa.String(length=512), nullable=True))
    op.add_column('builds', sa.Column('log', sa.Text(), nullable=True))
    op.drop_column('builds', 'binary_path')


def downgrade() -> None:
    op.add_column('builds', sa.Column('binary_path', sa.String(length=512), nullable=True))
    op.drop_column('builds', 'log')
    op.drop_column('builds', 'assembly_key')
    op.drop_column('builds', 'binary_key')
