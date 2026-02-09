"""add expense item link

Revision ID: 041_add_expense_item_link
Revises: 040_add_item_inactive_by_user
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '041_add_expense_item_link'
down_revision = '040_add_item_inactive_by_user'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'expenses',
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id'), nullable=True)
    )
    op.add_column(
        'expenses',
        sa.Column('item_cost_applied', sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        'expenses',
        sa.Column('item_cost_applied_amount', sa.Float(), nullable=True)
    )
    op.add_column(
        'expenses',
        sa.Column('item_cost_applied_at', sa.DateTime(), nullable=True)
    )
    op.create_index('ix_expenses_item_id', 'expenses', ['item_id'])
    op.create_index('ix_expenses_item_cost_applied', 'expenses', ['item_cost_applied'])
    op.alter_column('expenses', 'item_cost_applied', server_default=None)


def downgrade():
    op.drop_index('ix_expenses_item_cost_applied', table_name='expenses')
    op.drop_index('ix_expenses_item_id', table_name='expenses')
    op.drop_column('expenses', 'item_cost_applied_at')
    op.drop_column('expenses', 'item_cost_applied_amount')
    op.drop_column('expenses', 'item_cost_applied')
    op.drop_column('expenses', 'item_id')
