"""add last_activity to users

Revision ID: 024_add_last_activity
Revises: 023_add_monthly_expense_budget
Create Date: 2025-10-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '024_add_last_activity'
down_revision = '023_add_monthly_expense_budget'
branch_labels = None
depends_on = None


def upgrade():
    # Add last_activity column to users table
    op.add_column('users', sa.Column('last_activity', sa.DateTime(), nullable=True))

    # Initialize last_activity with last_login value for existing users
    op.execute("UPDATE users SET last_activity = last_login WHERE last_login IS NOT NULL")
    op.execute("UPDATE users SET last_activity = created_at WHERE last_activity IS NULL")


def downgrade():
    op.drop_column('users', 'last_activity')
