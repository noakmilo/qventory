"""add previous item link for relist chains

Revision ID: 047_items_prev_item
Revises: 046_auto_relist_item_link
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "047_items_prev_item"
down_revision = "046_auto_relist_item_link"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("previous_item_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_items_previous_item_id", ["previous_item_id"])
    op.create_foreign_key(
        "fk_items_previous_item_id",
        "items",
        "items",
        ["previous_item_id"],
        ["id"]
    )


def downgrade():
    op.drop_constraint("fk_items_previous_item_id", "items", type_="foreignkey")
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_index("ix_items_previous_item_id")
        batch_op.drop_column("previous_item_id")
