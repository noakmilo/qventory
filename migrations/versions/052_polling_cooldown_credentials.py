"""polling cooldown on marketplace credentials

Revision ID: 052_polling_cooldown_credentials
Revises: 051_polling_logs
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "052_polling_cooldown_credentials"
down_revision = "051_polling_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "marketplace_credentials",
        sa.Column("poll_cooldown_until", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "marketplace_credentials",
        sa.Column("poll_cooldown_reason", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_marketplace_credentials_poll_cooldown_until",
        "marketplace_credentials",
        ["poll_cooldown_until"],
    )


def downgrade():
    op.drop_index("ix_marketplace_credentials_poll_cooldown_until", table_name="marketplace_credentials")
    op.drop_column("marketplace_credentials", "poll_cooldown_reason")
    op.drop_column("marketplace_credentials", "poll_cooldown_until")
