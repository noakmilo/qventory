"""allow null user_id in webhook_events

Revision ID: 015_allow_null_user_id_webhook_events
Revises: 014_add_webhook_tables
Create Date: 2025-10-20 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '015_allow_null_user_id_webhook_events'
down_revision = '014_add_webhook_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Allow NULL for user_id in webhook_events (for events where we can't determine user)
    op.alter_column('webhook_events', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade():
    # Revert to NOT NULL
    op.alter_column('webhook_events', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
