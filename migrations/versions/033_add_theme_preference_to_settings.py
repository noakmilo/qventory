"""add theme preference to settings

Revision ID: 033_add_theme_preference_to_settings
Revises: 032_add_plan_prices
Create Date: 2026-01-07 00:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '033_add_theme_preference_to_settings'
down_revision = '032_add_plan_prices'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'theme_preference' not in columns:
        op.add_column('settings', sa.Column('theme_preference', sa.String(length=20), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('settings')}
    if 'theme_preference' in columns:
        op.drop_column('settings', 'theme_preference')
