"""retired items table

Revision ID: 053_retired_items
Revises: 052_polling_cooldown_credentials
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "053_retired_items"
down_revision = "052_polling_cooldown_credentials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "retired_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sku", sa.String(), nullable=True),
        sa.Column("ebay_listing_id", sa.String(length=100), nullable=True),
        sa.Column("ebay_url", sa.String(), nullable=True),
        sa.Column("item_thumb", sa.String(), nullable=True),
        sa.Column("item_price", sa.Float(), nullable=True),
        sa.Column("item_cost", sa.Float(), nullable=True),
        sa.Column("supplier", sa.String(), nullable=True),
        sa.Column("location_code", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("purged_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_retired_items_user_id", "retired_items", ["user_id"])
    op.create_index("ix_retired_items_item_id", "retired_items", ["item_id"])
    op.create_index("ix_retired_items_status", "retired_items", ["status"])
    op.create_index("ix_retired_items_ebay_listing_id", "retired_items", ["ebay_listing_id"])
    op.create_index("ix_retired_items_supplier", "retired_items", ["supplier"])
    op.create_index("ix_retired_items_location_code", "retired_items", ["location_code"])


def downgrade():
    op.drop_index("ix_retired_items_location_code", table_name="retired_items")
    op.drop_index("ix_retired_items_supplier", table_name="retired_items")
    op.drop_index("ix_retired_items_ebay_listing_id", table_name="retired_items")
    op.drop_index("ix_retired_items_status", table_name="retired_items")
    op.drop_index("ix_retired_items_item_id", table_name="retired_items")
    op.drop_index("ix_retired_items_user_id", table_name="retired_items")
    op.drop_table("retired_items")
