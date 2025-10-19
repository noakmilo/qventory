"""add price decrease fields to auto_relist_rules

Revision ID: 012_add_price_decrease
Revises: 011_add_notifications
Create Date: 2025-10-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012_add_price_decrease'
down_revision = '011_add_notifications'
branch_labels = None
depends_on = None


def upgrade():
    # Add price decrease fields to auto_relist_rules table
    op.add_column('auto_relist_rules',
        sa.Column('enable_price_decrease', sa.Boolean(), nullable=True, server_default='0')
    )
    op.add_column('auto_relist_rules',
        sa.Column('price_decrease_type', sa.String(length=20), nullable=True)
    )
    op.add_column('auto_relist_rules',
        sa.Column('price_decrease_amount', sa.Float(), nullable=True)
    )
    op.add_column('auto_relist_rules',
        sa.Column('min_price', sa.Float(), nullable=True)
    )


def downgrade():
    # Remove price decrease fields from auto_relist_rules table
    op.drop_column('auto_relist_rules', 'min_price')
    op.drop_column('auto_relist_rules', 'price_decrease_amount')
    op.drop_column('auto_relist_rules', 'price_decrease_type')
    op.drop_column('auto_relist_rules', 'enable_price_decrease')
