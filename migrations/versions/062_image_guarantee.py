"""add image guarantee fields for items and sales

Revision ID: 062_image_guarantee
Revises: 061_ebay_listing_drafts
Create Date: 2026-03-21 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "062_image_guarantee"
down_revision = "061_ebay_listing_drafts"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    item_columns = _column_names(inspector, "items")
    if "image_status" not in item_columns:
        op.add_column(
            "items",
            sa.Column("image_status", sa.String(length=32), nullable=False, server_default="ready"),
        )
    if "image_attempts" not in item_columns:
        op.add_column(
            "items",
            sa.Column("image_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "image_next_retry_at" not in item_columns:
        op.add_column("items", sa.Column("image_next_retry_at", sa.DateTime(), nullable=True))
    if "image_last_error" not in item_columns:
        op.add_column("items", sa.Column("image_last_error", sa.Text(), nullable=True))
    if "image_pending_since" not in item_columns:
        op.add_column("items", sa.Column("image_pending_since", sa.DateTime(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("items")}
    if "ix_items_image_status" not in indexes:
        op.create_index("ix_items_image_status", "items", ["image_status"], unique=False)
    if "ix_items_image_next_retry_at" not in indexes:
        op.create_index("ix_items_image_next_retry_at", "items", ["image_next_retry_at"], unique=False)

    sale_columns = _column_names(inspector, "sales")
    if "sale_item_thumb" not in sale_columns:
        op.add_column("sales", sa.Column("sale_item_thumb", sa.String(), nullable=True))
    if "sale_image_status" not in sale_columns:
        op.add_column(
            "sales",
            sa.Column("sale_image_status", sa.String(length=32), nullable=False, server_default="ready"),
        )
    if "sale_image_attempts" not in sale_columns:
        op.add_column(
            "sales",
            sa.Column("sale_image_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "sale_image_next_retry_at" not in sale_columns:
        op.add_column("sales", sa.Column("sale_image_next_retry_at", sa.DateTime(), nullable=True))
    if "sale_image_last_error" not in sale_columns:
        op.add_column("sales", sa.Column("sale_image_last_error", sa.Text(), nullable=True))
    if "sale_ebay_url" not in sale_columns:
        op.add_column("sales", sa.Column("sale_ebay_url", sa.String(), nullable=True))
    if "sale_ebay_listing_id" not in sale_columns:
        op.add_column("sales", sa.Column("sale_ebay_listing_id", sa.String(length=100), nullable=True))

    sale_indexes = {index["name"] for index in inspector.get_indexes("sales")}
    if "ix_sales_sale_image_status" not in sale_indexes:
        op.create_index("ix_sales_sale_image_status", "sales", ["sale_image_status"], unique=False)
    if "ix_sales_sale_image_next_retry_at" not in sale_indexes:
        op.create_index("ix_sales_sale_image_next_retry_at", "sales", ["sale_image_next_retry_at"], unique=False)
    if "ix_sales_sale_ebay_listing_id" not in sale_indexes:
        op.create_index("ix_sales_sale_ebay_listing_id", "sales", ["sale_ebay_listing_id"], unique=False)

    op.execute(
        """
        UPDATE items
        SET image_status = CASE
            WHEN item_thumb IS NOT NULL AND TRIM(item_thumb) <> '' THEN 'ready'
            WHEN synced_from_ebay IS TRUE OR ebay_listing_id IS NOT NULL THEN 'pending'
            ELSE 'ready'
        END
        WHERE image_status IS NULL OR image_status = '';
        """
    )
    op.execute(
        """
        UPDATE items
        SET image_pending_since = COALESCE(image_pending_since, created_at)
        WHERE (item_thumb IS NULL OR TRIM(item_thumb) = '')
          AND (synced_from_ebay IS TRUE OR ebay_listing_id IS NOT NULL)
          AND image_pending_since IS NULL;
        """
    )
    op.execute(
        """
        UPDATE sales
        SET sale_item_thumb = item_thumb
        FROM items
        WHERE sales.item_id = items.id
          AND sales.user_id = items.user_id
          AND sales.sale_item_thumb IS NULL
          AND items.item_thumb IS NOT NULL
          AND TRIM(items.item_thumb) <> '';
        """
    )
    op.execute(
        """
        UPDATE sales
        SET sale_ebay_url = items.ebay_url,
            sale_ebay_listing_id = items.ebay_listing_id
        FROM items
        WHERE sales.item_id = items.id
          AND sales.user_id = items.user_id
          AND (
              sales.sale_ebay_url IS NULL
              OR sales.sale_ebay_listing_id IS NULL
          );
        """
    )
    op.execute(
        """
        UPDATE sales
        SET sale_image_status = CASE
            WHEN marketplace = 'ebay' AND sale_item_thumb IS NOT NULL AND TRIM(sale_item_thumb) <> '' THEN 'ready'
            WHEN marketplace = 'ebay' THEN 'pending'
            ELSE 'ready'
        END
        WHERE sale_image_status IS NULL OR sale_image_status = '';
        """
    )

    op.alter_column("items", "image_status", server_default=None)
    op.alter_column("items", "image_attempts", server_default=None)
    op.alter_column("sales", "sale_image_status", server_default=None)
    op.alter_column("sales", "sale_image_attempts", server_default=None)


def downgrade():
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("sales")}
    if "ix_sales_sale_image_next_retry_at" in indexes:
        op.drop_index("ix_sales_sale_image_next_retry_at", table_name="sales")
    if "ix_sales_sale_image_status" in indexes:
        op.drop_index("ix_sales_sale_image_status", table_name="sales")
    if "ix_sales_sale_ebay_listing_id" in indexes:
        op.drop_index("ix_sales_sale_ebay_listing_id", table_name="sales")
    op.drop_column("sales", "sale_image_last_error")
    op.drop_column("sales", "sale_image_next_retry_at")
    op.drop_column("sales", "sale_image_attempts")
    op.drop_column("sales", "sale_image_status")
    op.drop_column("sales", "sale_ebay_listing_id")
    op.drop_column("sales", "sale_ebay_url")
    op.drop_column("sales", "sale_item_thumb")

    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("items")}
    if "ix_items_image_next_retry_at" in indexes:
        op.drop_index("ix_items_image_next_retry_at", table_name="items")
    if "ix_items_image_status" in indexes:
        op.drop_index("ix_items_image_status", table_name="items")
    op.drop_column("items", "image_pending_since")
    op.drop_column("items", "image_last_error")
    op.drop_column("items", "image_next_retry_at")
    op.drop_column("items", "image_attempts")
    op.drop_column("items", "image_status")
