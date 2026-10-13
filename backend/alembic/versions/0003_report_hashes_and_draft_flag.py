"""report hashes and draft flag

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 17:47:29.630246
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.add_column(sa.Column('snapshot_sha256', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('pdf_sha256', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('is_draft', sa.Boolean(), nullable=False, server_default=sa.true()))



def downgrade() -> None:
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.drop_column('is_draft')
        batch_op.drop_column('pdf_sha256')
        batch_op.drop_column('snapshot_sha256')

