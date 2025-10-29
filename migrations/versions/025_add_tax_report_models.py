"""add tax report models

Revision ID: 025_add_tax_report_models
Revises: 024_add_last_activity
Create Date: 2025-10-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '025_add_tax_report_models'
down_revision = '024_add_last_activity'
branch_labels = None
depends_on = None


def upgrade():
    # Create tax_reports table
    op.create_table(
        'tax_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),

        # Report Metadata
        sa.Column('tax_year', sa.Integer(), nullable=False),
        sa.Column('report_type', sa.String(length=50), nullable=True),
        sa.Column('quarter', sa.Integer(), nullable=True),

        # Generation Timestamps
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(), nullable=True),

        # Status
        sa.Column('status', sa.String(length=20), nullable=True),

        # Revenue Summary
        sa.Column('gross_sales_revenue', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_sales_count', sa.Integer(), nullable=True),
        sa.Column('marketplace_sales', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Additional Revenue
        sa.Column('additional_revenue', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('shipping_revenue', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('credits_adjustments', sa.Numeric(precision=10, scale=2), nullable=True),

        # Refunds/Returns
        sa.Column('total_refunds', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_returns', sa.Numeric(precision=10, scale=2), nullable=True),

        # Business Income
        sa.Column('business_income', sa.Numeric(precision=10, scale=2), nullable=True),

        # COGS
        sa.Column('total_cogs', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('cogs_items_count', sa.Integer(), nullable=True),
        sa.Column('cogs_missing_count', sa.Integer(), nullable=True),

        # Inventory
        sa.Column('opening_inventory_value', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('closing_inventory_value', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('inventory_purchased', sa.Numeric(precision=10, scale=2), nullable=True),

        # Business Expenses
        sa.Column('total_marketplace_fees', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('marketplace_fees_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('total_shipping_costs', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('shipping_costs_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('total_business_expenses', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('expense_categories_breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('payment_processing_fees', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_expenses', sa.Numeric(precision=10, scale=2), nullable=True),

        # Net Profit/Loss
        sa.Column('gross_profit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('net_profit', sa.Numeric(precision=10, scale=2), nullable=True),

        # Tax Estimates
        sa.Column('estimated_self_employment_tax', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('estimated_income_tax', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('estimated_quarterly_tax', sa.Numeric(precision=10, scale=2), nullable=True),

        # Data Quality
        sa.Column('validation_warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('missing_purchase_dates_count', sa.Integer(), nullable=True),
        sa.Column('missing_costs_count', sa.Integer(), nullable=True),
        sa.Column('receipts_without_association_count', sa.Integer(), nullable=True),
        sa.Column('data_completeness_score', sa.Numeric(precision=5, scale=2), nullable=True),

        # Detailed Breakdown
        sa.Column('detailed_sales', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('detailed_expenses', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Export History
        sa.Column('exported_formats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_exported_at', sa.DateTime(), nullable=True),

        # Notes
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('cpa_email', sa.String(length=255), nullable=True),

        # Primary key
        sa.PrimaryKeyConstraint('id'),

        # Foreign keys
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),

        # Constraints
        sa.UniqueConstraint('user_id', 'tax_year', 'report_type', 'quarter', name='unique_user_tax_report')
    )

    # Create indexes
    op.create_index('idx_tax_reports_user_year', 'tax_reports', ['user_id', 'tax_year'])
    op.create_index(op.f('ix_tax_reports_tax_year'), 'tax_reports', ['tax_year'], unique=False)

    # Create tax_report_exports table
    op.create_table(
        'tax_report_exports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tax_report_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),

        sa.Column('export_format', sa.String(length=50), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),

        sa.Column('exported_at', sa.DateTime(), nullable=False),
        sa.Column('downloaded_at', sa.DateTime(), nullable=True),

        sa.Column('export_parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Primary key
        sa.PrimaryKeyConstraint('id'),

        # Foreign keys
        sa.ForeignKeyConstraint(['tax_report_id'], ['tax_reports.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )


def downgrade():
    op.drop_table('tax_report_exports')
    op.drop_index('idx_tax_reports_user_year', table_name='tax_reports')
    op.drop_index(op.f('ix_tax_reports_tax_year'), table_name='tax_reports')
    op.drop_table('tax_reports')
