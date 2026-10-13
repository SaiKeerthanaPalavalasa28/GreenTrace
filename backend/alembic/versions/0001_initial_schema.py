"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-13 16:27:41.500459
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('organization',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('reporting_framework', sa.String(length=20), nullable=False),
    sa.Column('default_region', sa.String(length=40), nullable=False),
    sa.Column('fiscal_year_start_month', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organization'))
    )
    op.create_table('app_user',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=100), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_app_user_org_id_organization')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('email', name=op.f('uq_app_user_email'))
    )
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_app_user_org_id'), ['org_id'], unique=False)

    op.create_table('audit_log',
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('actor', sa.String(length=100), nullable=False),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('entity', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=100), nullable=False),
    sa.Column('before_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('after_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_audit_log_org_id_organization')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_org_id'), ['org_id'], unique=False)

    op.create_table('emission_factor',
    sa.Column('factor_key', sa.String(length=100), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=True),
    sa.Column('utility_type', sa.String(length=20), nullable=False),
    sa.Column('region', sa.String(length=40), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('kgco2e_per_unit', sa.Numeric(precision=24, scale=12), nullable=False),
    sa.Column('ghg_basis', sa.String(length=10), nullable=False),
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('source_name', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('publication_year', sa.Integer(), nullable=False),
    sa.Column('published_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('derivation', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('superseded_by', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_emission_factor_org_id_organization')),
    sa.ForeignKeyConstraint(['superseded_by'], ['emission_factor.id'], name=op.f('fk_emission_factor_superseded_by_emission_factor')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_emission_factor')),
    sa.UniqueConstraint('factor_key', 'version', name='uq_factor_key_version')
    )
    with op.batch_alter_table('emission_factor', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_emission_factor_factor_key'), ['factor_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_emission_factor_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_emission_factor_region'), ['region'], unique=False)

    op.create_table('facility',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('address', sa.String(length=500), nullable=False),
    sa.Column('region', sa.String(length=40), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_facility_org_id_organization')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_facility')),
    sa.UniqueConstraint('org_id', 'name', name='uq_facility_org_name')
    )
    with op.batch_alter_table('facility', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_facility_org_id'), ['org_id'], unique=False)

    op.create_table('bill',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('facility_id', sa.Uuid(), nullable=False),
    sa.Column('original_filename', sa.String(length=300), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_hash', sa.String(length=64), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('utility_type', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['facility_id'], ['facility.id'], name=op.f('fk_bill_facility_id_facility')),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_bill_org_id_organization')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['app_user.id'], name=op.f('fk_bill_uploaded_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bill')),
    sa.UniqueConstraint('org_id', 'file_hash', name='uq_bill_org_hash')
    )
    with op.batch_alter_table('bill', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bill_facility_id'), ['facility_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bill_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bill_status'), ['status'], unique=False)

    op.create_table('facility_account',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('facility_id', sa.Uuid(), nullable=False),
    sa.Column('utility_type', sa.String(length=20), nullable=False),
    sa.Column('account_number', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['facility_id'], ['facility.id'], name=op.f('fk_facility_account_facility_id_facility')),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_facility_account_org_id_organization')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_facility_account')),
    sa.UniqueConstraint('org_id', 'utility_type', 'account_number', name='uq_facility_account')
    )
    with op.batch_alter_table('facility_account', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_facility_account_org_id'), ['org_id'], unique=False)

    op.create_table('report',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('reporting_period_label', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('generated_by', sa.Uuid(), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('file_path', sa.String(length=500), nullable=True),
    sa.Column('snapshot_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['generated_by'], ['app_user.id'], name=op.f('fk_report_generated_by_app_user')),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], name=op.f('fk_report_org_id_organization')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report'))
    )
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_report_org_id'), ['org_id'], unique=False)

    op.create_table('extraction',
    sa.Column('bill_id', sa.Uuid(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('provider_name', sa.String(length=200), nullable=True),
    sa.Column('account_number', sa.String(length=100), nullable=True),
    sa.Column('billing_period_start', sa.Date(), nullable=True),
    sa.Column('billing_period_end', sa.Date(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('meter_previous', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('meter_current', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('meter_multiplier', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('read_type', sa.String(length=20), nullable=True),
    sa.Column('multiple_meters', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('raw_text_snippet', sa.Text(), nullable=True),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('text_method', sa.String(length=20), nullable=True),
    sa.Column('model_used', sa.String(length=100), nullable=True),
    sa.Column('validation_issues_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('corrections_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['bill_id'], ['bill.id'], name=op.f('fk_extraction_bill_id_bill')),
    sa.ForeignKeyConstraint(['reviewed_by'], ['app_user.id'], name=op.f('fk_extraction_reviewed_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extraction'))
    )
    with op.batch_alter_table('extraction', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_extraction_bill_id'), ['bill_id'], unique=False)

    op.create_table('emission_record',
    sa.Column('extraction_id', sa.Uuid(), nullable=False),
    sa.Column('emission_factor_id', sa.Uuid(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('allocation_start', sa.Date(), nullable=False),
    sa.Column('allocation_end', sa.Date(), nullable=False),
    sa.Column('allocation_fraction', sa.Numeric(precision=24, scale=12), nullable=False),
    sa.Column('normalized_quantity', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('normalized_unit', sa.String(length=20), nullable=False),
    sa.Column('kgco2e', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('scope', sa.Integer(), nullable=False),
    sa.Column('calculation_trace_json', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['emission_factor_id'], ['emission_factor.id'], name=op.f('fk_emission_record_emission_factor_id_emission_factor')),
    sa.ForeignKeyConstraint(['extraction_id'], ['extraction.id'], name=op.f('fk_emission_record_extraction_id_extraction')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_emission_record'))
    )
    with op.batch_alter_table('emission_record', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_emission_record_extraction_id'), ['extraction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_emission_record_is_current'), ['is_current'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('emission_record', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_emission_record_is_current'))
        batch_op.drop_index(batch_op.f('ix_emission_record_extraction_id'))

    op.drop_table('emission_record')
    with op.batch_alter_table('extraction', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_extraction_bill_id'))

    op.drop_table('extraction')
    with op.batch_alter_table('report', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_report_org_id'))

    op.drop_table('report')
    with op.batch_alter_table('facility_account', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_facility_account_org_id'))

    op.drop_table('facility_account')
    with op.batch_alter_table('bill', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bill_status'))
        batch_op.drop_index(batch_op.f('ix_bill_org_id'))
        batch_op.drop_index(batch_op.f('ix_bill_facility_id'))

    op.drop_table('bill')
    with op.batch_alter_table('facility', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_facility_org_id'))

    op.drop_table('facility')
    with op.batch_alter_table('emission_factor', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_emission_factor_region'))
        batch_op.drop_index(batch_op.f('ix_emission_factor_org_id'))
        batch_op.drop_index(batch_op.f('ix_emission_factor_factor_key'))

    op.drop_table('emission_factor')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_org_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_entity_id'))

    op.drop_table('audit_log')
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_app_user_org_id'))

    op.drop_table('app_user')
    op.drop_table('organization')
