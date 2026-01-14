"""Add ebay_top_rated to marketplace_credentials.

Revision ID: 035_add_ebay_top_rated_to_credentials
Revises: 034_add_sale_tax_collected
Create Date: 2025-01-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '035_add_ebay_top_rated_to_credentials'
down_revision = '034_add_sale_tax_collected'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('marketplace_credentials', sa.Column('ebay_top_rated', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.alter_column('marketplace_credentials', 'ebay_top_rated', server_default=None)


def downgrade():
    op.drop_column('marketplace_credentials', 'ebay_top_rated')
