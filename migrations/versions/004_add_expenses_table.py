"""add expenses table

Revision ID: 004_add_expenses_table
Revises: 003_add_ebay_store_subscription
Create Date: 2025-10-09 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_expenses_table'
down_revision = '003_add_ebay_store_subscription'
branch_labels = None
depends_on = None


def upgrade():
    # Create expenses table
    op.create_table('expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('is_recurring', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('recurring_frequency', sa.String(length=20), nullable=True),
        sa.Column('recurring_day', sa.Integer(), nullable=True),
        sa.Column('recurring_until', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index(op.f('ix_expenses_user_id'), 'expenses', ['user_id'], unique=False)
    op.create_index(op.f('ix_expenses_expense_date'), 'expenses', ['expense_date'], unique=False)
    op.create_index(op.f('ix_expenses_category'), 'expenses', ['category'], unique=False)
    op.create_index(op.f('ix_expenses_is_recurring'), 'expenses', ['is_recurring'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_expenses_is_recurring'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_category'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_expense_date'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_user_id'), table_name='expenses')
    op.drop_table('expenses')
