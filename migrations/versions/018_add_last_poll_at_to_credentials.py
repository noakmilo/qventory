"""Add last_poll_at to marketplace_credentials

Revision ID: 018_add_last_poll_at
Revises: 017_fix_cascade_delete
Create Date: 2025-10-20 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '018_add_last_poll_at'
down_revision = '017_fix_cascade_delete'
branch_labels = None
depends_on = None


def upgrade():
    # Add last_poll_at column for smart polling
    op.add_column('marketplace_credentials',
                  sa.Column('last_poll_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('marketplace_credentials', 'last_poll_at')
