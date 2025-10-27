"""add monthly_expense_budget to users

Revision ID: 023_add_monthly_expense_budget
Revises: 022_fix_receipt_usage_cascade
Create Date: 2025-01-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '023_add_monthly_expense_budget'
down_revision = '022_fix_receipt_usage_cascade'
branch_labels = None
depends_on = None


def upgrade():
    # Add monthly_expense_budget column to users table
    op.add_column('users', sa.Column('monthly_expense_budget', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade():
    # Remove monthly_expense_budget column from users table
    op.drop_column('users', 'monthly_expense_budget')
