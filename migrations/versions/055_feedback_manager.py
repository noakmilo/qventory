"""feedback manager

Revision ID: 055_feedback_manager
Revises: 054_slow_movers_settings
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "055_feedback_manager"
down_revision = "054_slow_movers_settings"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, "ebay_feedback"):
        op.create_table(
            "ebay_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("feedback_id", sa.String(length=64), nullable=False),
            sa.Column("comment_type", sa.String(length=20)),
            sa.Column("comment_text", sa.Text()),
            sa.Column("comment_time", sa.DateTime()),
            sa.Column("commenting_user", sa.String(length=80)),
            sa.Column("role", sa.String(length=40)),
            sa.Column("item_id", sa.String(length=40)),
            sa.Column("transaction_id", sa.String(length=40)),
            sa.Column("order_line_item_id", sa.String(length=80)),
            sa.Column("item_title", sa.String(length=255)),
            sa.Column("response_text", sa.Text()),
            sa.Column("response_type", sa.String(length=20)),
            sa.Column("response_time", sa.DateTime()),
            sa.Column("responded", sa.Boolean(), default=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "feedback_id", name="uq_ebay_feedback_user_feedback"),
        )
        op.create_index("idx_ebay_feedback_user_time", "ebay_feedback", ["user_id", "comment_time"])

    op.add_column("settings", sa.Column("feedback_manager_enabled", sa.Boolean(), nullable=True))
    op.add_column("settings", sa.Column("feedback_last_viewed_at", sa.DateTime(), nullable=True))
    op.add_column("settings", sa.Column("feedback_last_sync_at", sa.DateTime(), nullable=True))
    op.add_column("settings", sa.Column("feedback_backfill_completed", sa.Boolean(), nullable=True))

    op.execute("UPDATE settings SET feedback_manager_enabled = FALSE WHERE feedback_manager_enabled IS NULL")
    op.execute("UPDATE settings SET feedback_backfill_completed = FALSE WHERE feedback_backfill_completed IS NULL")


def downgrade():
    op.drop_column("settings", "feedback_backfill_completed")
    op.drop_column("settings", "feedback_last_sync_at")
    op.drop_column("settings", "feedback_last_viewed_at")
    op.drop_column("settings", "feedback_manager_enabled")
    op.drop_index("idx_ebay_feedback_user_time", table_name="ebay_feedback")
    op.drop_table("ebay_feedback")
