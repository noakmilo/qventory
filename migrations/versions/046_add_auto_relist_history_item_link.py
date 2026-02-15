"""add item link to auto relist history

Revision ID: 046_auto_relist_item_link
Revises: 045_add_support_ticket_archived
Create Date: 2026-02-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "046_auto_relist_item_link"
down_revision = "045_add_support_ticket_archived"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("auto_relist_history") as batch_op:
        batch_op.add_column(sa.Column("item_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sku", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("old_title", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("new_title", sa.String(length=500), nullable=True))
        batch_op.create_index("ix_auto_relist_history_item_id", ["item_id"])
        batch_op.create_index("ix_auto_relist_history_sku", ["sku"])

    op.create_foreign_key(
        "fk_auto_relist_history_item_id",
        "auto_relist_history",
        "items",
        ["item_id"],
        ["id"]
    )


def downgrade():
    op.drop_constraint("fk_auto_relist_history_item_id", "auto_relist_history", type_="foreignkey")
    with op.batch_alter_table("auto_relist_history") as batch_op:
        batch_op.drop_index("ix_auto_relist_history_sku")
        batch_op.drop_index("ix_auto_relist_history_item_id")
        batch_op.drop_column("new_title")
        batch_op.drop_column("old_title")
        batch_op.drop_column("sku")
        batch_op.drop_column("item_id")
