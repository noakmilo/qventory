"""add inventory source reactions

Revision ID: 067_inventory_source_reactions
Revises: 066_add_inventory_sources
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "067_inventory_source_reactions"
down_revision = "066_add_inventory_sources"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "inventory_source_reactions" not in existing_tables:
        op.create_table(
            "inventory_source_reactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("reaction", sa.String(length=10), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["source_id"], ["inventory_sources.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_id", "user_id", name="uq_inventory_source_reactions_source_user"),
        )
        existing_tables.add("inventory_source_reactions")

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_source_reactions")} if "inventory_source_reactions" in existing_tables else set()
    if "ix_inventory_source_reactions_source_id" not in indexes:
        op.create_index("ix_inventory_source_reactions_source_id", "inventory_source_reactions", ["source_id"], unique=False)
    if "ix_inventory_source_reactions_user_id" not in indexes:
        op.create_index("ix_inventory_source_reactions_user_id", "inventory_source_reactions", ["user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_source_reactions" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_source_reactions")}
    if "ix_inventory_source_reactions_user_id" in indexes:
        op.drop_index("ix_inventory_source_reactions_user_id", table_name="inventory_source_reactions")
    if "ix_inventory_source_reactions_source_id" in indexes:
        op.drop_index("ix_inventory_source_reactions_source_id", table_name="inventory_source_reactions")
    op.drop_table("inventory_source_reactions")
