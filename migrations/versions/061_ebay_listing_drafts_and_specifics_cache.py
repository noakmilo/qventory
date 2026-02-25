"""add ebay listing drafts and specifics cache

Revision ID: 061_ebay_listing_drafts_and_specifics_cache
Revises: 060_add_hidden_tasks_to_settings
Create Date: 2026-02-25 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "061_ebay_listing_drafts_and_specifics_cache"
down_revision = "060_add_hidden_tasks_to_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ebay_listing_drafts"):
        op.create_table(
            "ebay_listing_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT", index=True),
            sa.Column("title", sa.String(length=80), nullable=True),
            sa.Column("description_html", sa.Text(), nullable=True),
            sa.Column("description_html_sanitized", sa.Text(), nullable=True),
            sa.Column("description_text", sa.Text(), nullable=True),
            sa.Column("category_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("item_specifics_json", sa.JSON(), nullable=True),
            sa.Column("condition_id", sa.String(length=32), nullable=True),
            sa.Column("condition_label", sa.String(length=64), nullable=True),
            sa.Column("sku", sa.String(length=64), nullable=True, index=True),
            sa.Column("quantity", sa.Integer(), nullable=True),
            sa.Column("price", sa.Numeric(10, 2), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=True),
            sa.Column("location_postal_code", sa.String(length=16), nullable=True),
            sa.Column("location_city", sa.String(length=80), nullable=True),
            sa.Column("location_state", sa.String(length=32), nullable=True),
            sa.Column("location_country", sa.String(length=2), nullable=True),
            sa.Column("merchant_location_key", sa.String(length=64), nullable=True),
            sa.Column("fulfillment_policy_id", sa.String(length=64), nullable=True),
            sa.Column("payment_policy_id", sa.String(length=64), nullable=True),
            sa.Column("return_policy_id", sa.String(length=64), nullable=True),
            sa.Column("images_json", sa.JSON(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("ebay_listing_id", sa.String(length=100), nullable=True, index=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("ebay_category_specific_cache"):
        op.create_table(
            "ebay_category_specific_cache",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("category_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("marketplace_id", sa.String(length=32), nullable=False, index=True),
            sa.Column("required_fields_json", sa.JSON(), nullable=True),
            sa.Column("optional_fields_json", sa.JSON(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("source_version", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("category_id", "marketplace_id", name="uq_ebay_category_specific_cache"),
        )


def downgrade():
    op.drop_table("ebay_category_specific_cache")
    op.drop_table("ebay_listing_drafts")
