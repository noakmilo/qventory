"""add item inactive by user flag

Revision ID: 040_add_item_inactive_by_user
Revises: 039_add_support_tickets
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '040_add_item_inactive_by_user'
down_revision = '039_add_support_tickets'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'items',
        sa.Column('inactive_by_user', sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.alter_column('items', 'inactive_by_user', server_default=None)


def downgrade():
    op.drop_column('items', 'inactive_by_user')
