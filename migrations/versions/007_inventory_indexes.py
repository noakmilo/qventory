"""add performance indexes for inventory views

Revision ID: 007_inventory_indexes
Revises: 006_add_import_jobs_table
Create Date: 2025-10-11

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '007_inventory_indexes'
down_revision = '006_add_import_jobs_table'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_user_active_coalesced
        ON items (user_id, is_active, COALESCE(listing_date::timestamp, created_at))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sales_user_status_sold_at
        ON sales (user_id, status, sold_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sales_user_ship_deliv_event
        ON sales (
            user_id,
            GREATEST(
                COALESCE(delivered_at, '-infinity'::timestamp),
                COALESCE(shipped_at, '-infinity'::timestamp)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listings_item_status_ended_at
        ON listings (item_id, status, ended_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listings_item_listed_at
        ON listings (item_id, listed_at DESC)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_listings_item_listed_at")
    op.execute("DROP INDEX IF EXISTS idx_listings_item_status_ended_at")
    op.execute("DROP INDEX IF EXISTS idx_sales_user_ship_deliv_event")
    op.execute("DROP INDEX IF EXISTS idx_sales_user_status_sold_at")
    op.execute("DROP INDEX IF EXISTS idx_items_user_active_coalesced")
