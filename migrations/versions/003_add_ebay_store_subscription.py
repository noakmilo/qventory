"""add ebay store subscription

Revision ID: 003_add_ebay_store_subscription
Revises: 001_initial_schema
Create Date: 2025-10-09 22:49:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_add_ebay_store_subscription'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    # Add ebay_store_subscription field to marketplace_credentials table
    op.add_column('marketplace_credentials',
        sa.Column('ebay_store_subscription', sa.Float(), nullable=True, server_default='0.0')
    )


def downgrade():
    op.drop_column('marketplace_credentials', 'ebay_store_subscription')
