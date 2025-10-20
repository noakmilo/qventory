"""add_ebay_fields_to_items

Revision ID: 016_add_ebay_fields
Revises: 015_webhook_null_user_id
Create Date: 2025-10-20 17:35:09.660064

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016_add_ebay_fields'
down_revision = '015_webhook_null_user_id'
branch_labels = None
depends_on = None


def upgrade():
    # Add eBay-related columns to items table
    op.add_column('items', sa.Column('ebay_listing_id', sa.String(100), nullable=True))
    op.add_column('items', sa.Column('ebay_sku', sa.String(100), nullable=True))
    op.add_column('items', sa.Column('synced_from_ebay', sa.Boolean(), nullable=True, default=False))
    op.add_column('items', sa.Column('last_ebay_sync', sa.DateTime(), nullable=True))

    # Create indexes for better query performance
    op.create_index('ix_items_ebay_listing_id', 'items', ['ebay_listing_id'])
    op.create_index('ix_items_ebay_sku', 'items', ['ebay_sku'])


def downgrade():
    # Drop indexes
    op.drop_index('ix_items_ebay_sku', 'items')
    op.drop_index('ix_items_ebay_listing_id', 'items')

    # Drop columns
    op.drop_column('items', 'last_ebay_sync')
    op.drop_column('items', 'synced_from_ebay')
    op.drop_column('items', 'ebay_sku')
    op.drop_column('items', 'ebay_listing_id')
