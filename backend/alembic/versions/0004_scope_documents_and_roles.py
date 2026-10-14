"""scope documents and per-scope budgets

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.models.base import JSONType

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scope1_budget_t', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('scope2_budget_t', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('scope3_budget_t', sa.Float(), nullable=True))
    op.create_table('scope_document',
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('scope', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=300), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('items', JSONType, nullable=False),
        sa.Column('flags', JSONType, nullable=False),
        sa.Column('total_kg_co2e', sa.Float(), nullable=False),
        sa.Column('uploaded_by', sa.Uuid(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_scope_document_org_id_organization')),
        sa.ForeignKeyConstraint(['uploaded_by'], ['app_user.id'], name=op.f('fk_scope_document_uploaded_by_app_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scope_document')),
        sa.UniqueConstraint('org_id', 'file_hash', name='uq_scope_document_org_hash'),
    )
    op.create_index(op.f('ix_scope_document_org_id'), 'scope_document', ['org_id'])
    op.create_index(op.f('ix_scope_document_scope'), 'scope_document', ['scope'])


def downgrade() -> None:
    op.drop_table('scope_document')
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.drop_column('scope3_budget_t')
        batch_op.drop_column('scope2_budget_t')
        batch_op.drop_column('scope1_budget_t')
