"""add thrift radar saved searches

Revision ID: 069_thrift_radar_searches
Revises: 068_inventory_source_suggests
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "069_thrift_radar_searches"
down_revision = "068_inventory_source_suggests"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "thrift_radar_saved_searches" not in existing_tables:
        op.create_table(
            "thrift_radar_saved_searches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("zip_code", sa.String(length=10), nullable=False),
            sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("results", sa.JSON(), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("thrift_radar_saved_searches")

    indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_saved_searches")} if "thrift_radar_saved_searches" in existing_tables else set()
    if "ix_thrift_radar_saved_searches_is_archived" not in indexes:
        op.create_index("ix_thrift_radar_saved_searches_is_archived", "thrift_radar_saved_searches", ["is_archived"], unique=False)
    if "ix_thrift_radar_saved_searches_user_id" not in indexes:
        op.create_index("ix_thrift_radar_saved_searches_user_id", "thrift_radar_saved_searches", ["user_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "thrift_radar_saved_searches" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_saved_searches")}
    if "ix_thrift_radar_saved_searches_user_id" in indexes:
        op.drop_index("ix_thrift_radar_saved_searches_user_id", table_name="thrift_radar_saved_searches")
    if "ix_thrift_radar_saved_searches_is_archived" in indexes:
        op.drop_index("ix_thrift_radar_saved_searches_is_archived", table_name="thrift_radar_saved_searches")
    op.drop_table("thrift_radar_saved_searches")
