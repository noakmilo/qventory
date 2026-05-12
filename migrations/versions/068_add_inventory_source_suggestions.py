"""add inventory source suggestions

Revision ID: 068_add_inventory_source_suggestions
Revises: 067_add_inventory_source_reactions
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "068_add_inventory_source_suggestions"
down_revision = "067_add_inventory_source_reactions"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "inventory_source_suggestions" not in existing_tables:
        op.create_table(
            "inventory_source_suggestions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("link_url", sa.String(length=1000), nullable=False),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("archived_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["archived_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("inventory_source_suggestions")

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_source_suggestions")} if "inventory_source_suggestions" in existing_tables else set()
    if "ix_inventory_source_suggestions_is_archived" not in indexes:
        op.create_index("ix_inventory_source_suggestions_is_archived", "inventory_source_suggestions", ["is_archived"], unique=False)
    if "ix_inventory_source_suggestions_user_id" not in indexes:
        op.create_index("ix_inventory_source_suggestions_user_id", "inventory_source_suggestions", ["user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_source_suggestions" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_source_suggestions")}
    if "ix_inventory_source_suggestions_user_id" in indexes:
        op.drop_index("ix_inventory_source_suggestions_user_id", table_name="inventory_source_suggestions")
    if "ix_inventory_source_suggestions_is_archived" in indexes:
        op.drop_index("ix_inventory_source_suggestions_is_archived", table_name="inventory_source_suggestions")
    op.drop_table("inventory_source_suggestions")
