"""ebay fee snapshots

Revision ID: 050_ebay_fee_snapshot
Revises: 049_auto_relist_rule_nullable
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "050_ebay_fee_snapshot"
down_revision = "049_auto_relist_rule_nullable"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ebay_fee_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category_id", sa.String(length=64)),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("shipping_cost", sa.Float(), default=0.0),
        sa.Column("has_store", sa.Boolean(), default=False),
        sa.Column("top_rated", sa.Boolean(), default=False),
        sa.Column("fee_rate_percent", sa.Float(), default=0.0),
        sa.Column("total_fees", sa.Float(), default=0.0),
        sa.Column("fee_breakdown", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_ebay_fee_snapshots_user_id", "ebay_fee_snapshots", ["user_id"])
    op.create_index("ix_ebay_fee_snapshots_category_id", "ebay_fee_snapshots", ["category_id"])
    op.create_index("ix_ebay_fee_snapshots_created_at", "ebay_fee_snapshots", ["created_at"])


def downgrade():
    op.drop_index("ix_ebay_fee_snapshots_created_at", table_name="ebay_fee_snapshots")
    op.drop_index("ix_ebay_fee_snapshots_category_id", table_name="ebay_fee_snapshots")
    op.drop_index("ix_ebay_fee_snapshots_user_id", table_name="ebay_fee_snapshots")
    op.drop_table("ebay_fee_snapshots")
