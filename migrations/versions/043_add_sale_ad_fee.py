"""add sale ad_fee column

Revision ID: 043_add_sale_ad_fee
Revises: 042_add_item_cost_history
Create Date: 2026-02-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '043_add_sale_ad_fee'
down_revision = '042_add_item_cost_history'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sales', sa.Column('ad_fee', sa.Float(), nullable=True, server_default='0'))
    op.alter_column('sales', 'ad_fee', server_default=None)


def downgrade():
    op.drop_column('sales', 'ad_fee')
