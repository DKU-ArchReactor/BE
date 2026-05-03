"""files: add title lang timestamps

Revision ID: 5e62e48b1f36
Revises: c3622a14fbfd
Create Date: 2026-05-03 11:17:50.309257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e62e48b1f36'
down_revision: Union[str, None] = 'c3622a14fbfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'files',
        sa.Column('title', sa.String(length=255), nullable=False, server_default='untitled'),
    )
    op.alter_column('files', 'title', server_default=None)

    op.alter_column('files', 'language', new_column_name='lang', existing_type=sa.String(length=16))

    op.add_column(
        'files',
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.add_column(
        'files',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_unique_constraint('uq_files_project_title', 'files', ['project_id', 'title'])


def downgrade() -> None:
    op.drop_constraint('uq_files_project_title', 'files', type_='unique')
    op.drop_column('files', 'updated_at')
    op.drop_column('files', 'created_at')
    op.alter_column('files', 'lang', new_column_name='language', existing_type=sa.String(length=16))
    op.drop_column('files', 'title')
