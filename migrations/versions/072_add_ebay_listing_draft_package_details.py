"""add ebay listing draft package and listing options

Revision ID: 072_ebay_listing_draft_package
Revises: 071_thrift_radar_google
Create Date: 2026-05-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "072_ebay_listing_draft_package"
down_revision = "071_thrift_radar_google"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ebay_listing_drafts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    column_defs = {
        "package_details_json": sa.Column("package_details_json", sa.JSON(), nullable=True),
        "listing_format": sa.Column("listing_format", sa.String(length=20), nullable=False, server_default="FIXED_PRICE"),
        "accept_offers": sa.Column("accept_offers", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        "auction_start_price": sa.Column("auction_start_price", sa.Numeric(10, 2), nullable=True),
    }
    for name, column in column_defs.items():
        if name not in columns:
            op.add_column("ebay_listing_drafts", column)

    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    if "listing_format" in columns:
        op.alter_column("ebay_listing_drafts", "listing_format", server_default=None)
    if "accept_offers" in columns:
        op.alter_column("ebay_listing_drafts", "accept_offers", server_default=None)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ebay_listing_drafts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    for name in ("auction_start_price", "accept_offers", "listing_format", "package_details_json"):
        if name in columns:
            op.drop_column("ebay_listing_drafts", name)
