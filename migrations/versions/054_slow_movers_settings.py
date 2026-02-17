"""slow movers settings

Revision ID: 054_slow_movers_settings
Revises: 053_retired_items
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "054_slow_movers_settings"
down_revision = "053_retired_items"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("settings", sa.Column("slow_movers_enabled", sa.Boolean(), nullable=True))
    op.add_column("settings", sa.Column("slow_movers_days", sa.Integer(), nullable=True))
    op.add_column("settings", sa.Column("slow_movers_start_mode", sa.String(length=20), nullable=True))
    op.add_column("settings", sa.Column("slow_movers_start_date", sa.Date(), nullable=True))

    op.execute("UPDATE settings SET slow_movers_enabled = FALSE WHERE slow_movers_enabled IS NULL")
    op.execute("UPDATE settings SET slow_movers_days = 30 WHERE slow_movers_days IS NULL")
    op.execute("UPDATE settings SET slow_movers_start_mode = 'item_added' WHERE slow_movers_start_mode IS NULL")


def downgrade():
    op.drop_column("settings", "slow_movers_start_date")
    op.drop_column("settings", "slow_movers_start_mode")
    op.drop_column("settings", "slow_movers_days")
    op.drop_column("settings", "slow_movers_enabled")
