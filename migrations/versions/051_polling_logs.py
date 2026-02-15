"""polling logs

Revision ID: 051_polling_logs
Revises: 050_ebay_fee_snapshot
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "051_polling_logs"
down_revision = "050_ebay_fee_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "polling_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("marketplace", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("new_listings", sa.Integer(), default=0),
        sa.Column("errors_count", sa.Integer(), default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_polling_logs_user_id", "polling_logs", ["user_id"])
    op.create_index("ix_polling_logs_marketplace", "polling_logs", ["marketplace"])
    op.create_index("ix_polling_logs_status", "polling_logs", ["status"])
    op.create_index("ix_polling_logs_created_at", "polling_logs", ["created_at"])


def downgrade():
    op.drop_index("ix_polling_logs_created_at", table_name="polling_logs")
    op.drop_index("ix_polling_logs_status", table_name="polling_logs")
    op.drop_index("ix_polling_logs_marketplace", table_name="polling_logs")
    op.drop_index("ix_polling_logs_user_id", table_name="polling_logs")
    op.drop_table("polling_logs")
