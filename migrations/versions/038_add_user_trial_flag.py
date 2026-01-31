"""add user trial flag

Revision ID: 038_add_user_trial_flag
Revises: 037_add_pickup_scheduler
Create Date: 2026-01-31
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '038_add_user_trial_flag'
down_revision = '037_add_pickup_scheduler'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('has_used_trial', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('users', 'has_used_trial', server_default=None)


def downgrade():
    op.drop_column('users', 'has_used_trial')
