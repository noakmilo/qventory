"""add archive fields to retired items

Revision ID: 076_retired_items_archive
Revises: 075_pending_registrations
Create Date: 2026-05-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "076_retired_items_archive"
down_revision = "075_pending_registrations"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "retired_items" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("retired_items")}
    indexes = {idx["name"] for idx in inspector.get_indexes("retired_items")}

    if "is_archived" not in columns:
        op.add_column(
            "retired_items",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if "archived_at" not in columns:
        op.add_column("retired_items", sa.Column("archived_at", sa.DateTime(), nullable=True))
    if "ix_retired_items_is_archived" not in indexes:
        op.create_index("ix_retired_items_is_archived", "retired_items", ["is_archived"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "retired_items" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("retired_items")}
    indexes = {idx["name"] for idx in inspector.get_indexes("retired_items")}

    if "ix_retired_items_is_archived" in indexes:
        op.drop_index("ix_retired_items_is_archived", table_name="retired_items")
    if "archived_at" in columns:
        op.drop_column("retired_items", "archived_at")
    if "is_archived" in columns:
        op.drop_column("retired_items", "is_archived")
