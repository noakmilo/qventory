"""add plan prices

Revision ID: 032_add_plan_prices
Revises: 031_add_help_articles
Create Date: 2026-01-06 23:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '032_add_plan_prices'
down_revision = '031_add_help_articles'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('plan_limits')}
    if 'monthly_price' not in columns:
        op.add_column('plan_limits', sa.Column('monthly_price', sa.Numeric(10, 2), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('plan_limits')}
    if 'monthly_price' in columns:
        op.drop_column('plan_limits', 'monthly_price')
