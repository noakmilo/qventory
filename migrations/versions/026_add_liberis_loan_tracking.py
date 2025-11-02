"""Add Liberis loan tracking

Revision ID: 026_add_liberis_loan_tracking
Revises: 025_add_tax_report_models
Create Date: 2025-11-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '026_add_liberis_loan_tracking'
down_revision = '025_add_tax_report_models'
branch_labels = None
depends_on = None


def upgrade():
    # Create liberis_loans table
    op.create_table(
        'liberis_loans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False, comment='Percentage fee charged on sales (e.g., 17.0 for 17%)'),
        sa.Column('start_date', sa.Date(), nullable=False, comment='Date when the loan repayment started'),
        sa.Column('total_amount', sa.Float(), nullable=False, comment='Total amount to repay to Liberis'),
        sa.Column('paid_amount', sa.Float(), nullable=False, default=0, comment='Amount already paid (calculated from sales)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True, comment='Whether the loan is currently active'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True, comment='Date when the loan was fully paid'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )

    op.create_index('ix_liberis_loans_user_id', 'liberis_loans', ['user_id'])
    op.create_index('ix_liberis_loans_is_active', 'liberis_loans', ['is_active'])


def downgrade():
    op.drop_index('ix_liberis_loans_is_active', table_name='liberis_loans')
    op.drop_index('ix_liberis_loans_user_id', table_name='liberis_loans')
    op.drop_table('liberis_loans')
