"""add system settings table

Revision ID: 029_sys_settings
Revises: 028_store_sub_lvl
Create Date: 2026-01-06
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '029_sys_settings'
down_revision = '028_store_sub_lvl'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'system_settings' in inspector.get_table_names():
        return
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(length=100), primary_key=True),
        sa.Column('value_int', sa.Integer(), nullable=True),
        sa.Column('value_str', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True)
    )


def downgrade():
    op.drop_table('system_settings')
