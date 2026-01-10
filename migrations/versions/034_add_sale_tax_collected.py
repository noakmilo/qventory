"""add sale tax collected

Revision ID: 034_add_sale_tax_collected
Revises: 033_add_theme_pref
Create Date: 2026-01-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '034_add_sale_tax_collected'
down_revision = '033_add_theme_pref'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sales', sa.Column('tax_collected', sa.Float(), nullable=True, server_default='0'))
    op.alter_column('sales', 'tax_collected', server_default=None)


def downgrade():
    op.drop_column('sales', 'tax_collected')
