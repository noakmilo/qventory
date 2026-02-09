"""add item cost history

Revision ID: 042_add_item_cost_history
Revises: 041_add_expense_item_link
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '042_add_item_cost_history'
down_revision = '041_add_expense_item_link'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'item_cost_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('items.id'), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('previous_cost', sa.Float(), nullable=True),
        sa.Column('new_cost', sa.Float(), nullable=True),
        sa.Column('delta', sa.Float(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_item_cost_history_user_id', 'item_cost_history', ['user_id'])
    op.create_index('ix_item_cost_history_item_id', 'item_cost_history', ['item_id'])
    op.create_index('ix_item_cost_history_created_at', 'item_cost_history', ['created_at'])
    op.alter_column('item_cost_history', 'source', server_default=None)


def downgrade():
    op.drop_index('ix_item_cost_history_created_at', table_name='item_cost_history')
    op.drop_index('ix_item_cost_history_item_id', table_name='item_cost_history')
    op.drop_index('ix_item_cost_history_user_id', table_name='item_cost_history')
    op.drop_table('item_cost_history')
