"""ensure ebay listing draft listing options

Revision ID: 073_ebay_draft_listing_opts
Revises: 072_ebay_listing_draft_package
Create Date: 2026-05-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "073_ebay_draft_listing_opts"
down_revision = "072_ebay_listing_draft_package"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ebay_listing_drafts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    if "listing_format" not in columns:
        op.add_column(
            "ebay_listing_drafts",
            sa.Column("listing_format", sa.String(length=20), nullable=False, server_default="FIXED_PRICE"),
        )
        op.alter_column("ebay_listing_drafts", "listing_format", server_default=None)

    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    if "accept_offers" not in columns:
        op.add_column(
            "ebay_listing_drafts",
            sa.Column("accept_offers", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.alter_column("ebay_listing_drafts", "accept_offers", server_default=None)

    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    if "auction_start_price" not in columns:
        op.add_column(
            "ebay_listing_drafts",
            sa.Column("auction_start_price", sa.Numeric(10, 2), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ebay_listing_drafts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    for name in ("auction_start_price", "accept_offers", "listing_format"):
        if name in columns:
            op.drop_column("ebay_listing_drafts", name)
