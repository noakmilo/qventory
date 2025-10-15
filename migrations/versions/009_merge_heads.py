"""merge multiple heads

Revision ID: 009_merge_heads
Revises: 008_add_auto_relist_tables, d83839f86a9f
Create Date: 2025-10-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009_merge_heads'
down_revision = ('008_add_auto_relist_tables', 'd83839f86a9f')
branch_labels = None
depends_on = None


def upgrade():
    # This is a merge migration - no schema changes needed
    pass


def downgrade():
    # This is a merge migration - no schema changes needed
    pass
