"""add ebay store subscription level

Revision ID: 028_add_ebay_store_subscription_level
Revises: 027_unique_ebay_listing
Create Date: 2025-11-05
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '028_add_ebay_store_subscription_level'
down_revision = '027_unique_ebay_listing'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('marketplace_credentials',
        sa.Column('ebay_store_subscription_level', sa.String(length=50), nullable=True)
    )


def downgrade():
    op.drop_column('marketplace_credentials', 'ebay_store_subscription_level')
