"""add inventory sources

Revision ID: 066_add_inventory_sources
Revises: 065_polling_logs_user_cascade
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "066_add_inventory_sources"
down_revision = "065_polling_logs_user_cascade"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "inventory_sources" not in existing_tables:
        op.create_table(
            "inventory_sources",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("image_url", sa.String(length=1000), nullable=True),
            sa.Column("link_url", sa.String(length=1000), nullable=False),
            sa.Column("allowed_roles", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("inventory_sources")

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_sources")} if "inventory_sources" in existing_tables else set()
    if "ix_inventory_sources_is_active" not in indexes:
        op.create_index("ix_inventory_sources_is_active", "inventory_sources", ["is_active"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventory_sources" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("inventory_sources")}
    if "ix_inventory_sources_is_active" in indexes:
        op.drop_index("ix_inventory_sources_is_active", table_name="inventory_sources")
    op.drop_table("inventory_sources")
