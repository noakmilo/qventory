"""add ebay listing draft package details

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
    if "package_details_json" not in columns:
        op.add_column("ebay_listing_drafts", sa.Column("package_details_json", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ebay_listing_drafts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ebay_listing_drafts")}
    if "package_details_json" in columns:
        op.drop_column("ebay_listing_drafts", "package_details_json")
