"""profit calculator reports and ebay taxonomy

Revision ID: 048_profit_calc
Revises: 047_items_prev_item
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "048_profit_calc"
down_revision = "047_items_prev_item"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ebay_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_id", sa.String(length=64)),
        sa.Column("full_path", sa.String(length=1000), nullable=False),
        sa.Column("level", sa.Integer(), default=0),
        sa.Column("is_leaf", sa.Boolean(), default=False),
        sa.Column("tree_id", sa.String(length=64)),
        sa.Column("tree_version", sa.String(length=64)),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_ebay_categories_category_id", "ebay_categories", ["category_id"], unique=True)
    op.create_index("ix_ebay_categories_name", "ebay_categories", ["name"])
    op.create_index("ix_ebay_categories_parent_id", "ebay_categories", ["parent_id"])
    op.create_index("ix_ebay_categories_full_path", "ebay_categories", ["full_path"])

    op.create_table(
        "ebay_fee_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.String(length=64)),
        sa.Column("standard_rate", sa.Float(), nullable=False),
        sa.Column("store_rate", sa.Float()),
        sa.Column("top_rated_discount", sa.Float(), default=10.0),
        sa.Column("fixed_fee", sa.Float(), default=0.30),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_ebay_fee_rules_category_id", "ebay_fee_rules", ["category_id"])

    op.create_table(
        "profit_calculator_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("marketplace", sa.String(length=20), nullable=False),
        sa.Column("item_name", sa.String(length=500)),
        sa.Column("category_id", sa.String(length=64)),
        sa.Column("category_path", sa.String(length=1000)),
        sa.Column("buy_price", sa.Float(), nullable=False),
        sa.Column("resale_price", sa.Float(), nullable=False),
        sa.Column("shipping_cost", sa.Float(), default=0.0),
        sa.Column("has_store", sa.Boolean(), default=False),
        sa.Column("top_rated", sa.Boolean(), default=False),
        sa.Column("include_fixed_fee", sa.Boolean(), default=False),
        sa.Column("ads_fee_rate", sa.Float(), default=0.0),
        sa.Column("fee_breakdown", sa.JSON()),
        sa.Column("total_fees", sa.Float(), default=0.0),
        sa.Column("net_sale", sa.Float(), default=0.0),
        sa.Column("profit", sa.Float(), default=0.0),
        sa.Column("roi", sa.Float(), default=0.0),
        sa.Column("markup", sa.Float(), default=0.0),
        sa.Column("breakeven", sa.Float(), default=0.0),
        sa.Column("output_text", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_profit_calculator_reports_user_id", "profit_calculator_reports", ["user_id"])
    op.create_index("ix_profit_calculator_reports_marketplace", "profit_calculator_reports", ["marketplace"])
    op.create_index("ix_profit_calculator_reports_created_at", "profit_calculator_reports", ["created_at"])

    op.execute(
        "INSERT INTO ebay_fee_rules (category_id, standard_rate, store_rate, top_rated_discount, fixed_fee) "
        "VALUES (NULL, 13.25, 11.5, 10.0, 0.30)"
    )


def downgrade():
    op.drop_index("ix_profit_calculator_reports_created_at", table_name="profit_calculator_reports")
    op.drop_index("ix_profit_calculator_reports_marketplace", table_name="profit_calculator_reports")
    op.drop_index("ix_profit_calculator_reports_user_id", table_name="profit_calculator_reports")
    op.drop_table("profit_calculator_reports")

    op.drop_index("ix_ebay_fee_rules_category_id", table_name="ebay_fee_rules")
    op.drop_table("ebay_fee_rules")

    op.drop_index("ix_ebay_categories_full_path", table_name="ebay_categories")
    op.drop_index("ix_ebay_categories_parent_id", table_name="ebay_categories")
    op.drop_index("ix_ebay_categories_name", table_name="ebay_categories")
    op.drop_index("ix_ebay_categories_category_id", table_name="ebay_categories")
    op.drop_table("ebay_categories")
