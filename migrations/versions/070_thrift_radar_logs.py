"""add thrift radar logs

Revision ID: 070_thrift_radar_logs
Revises: 069_thrift_radar_searches
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "070_thrift_radar_logs"
down_revision = "069_thrift_radar_searches"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "thrift_radar_logs" not in existing_tables:
        op.create_table(
            "thrift_radar_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("saved_search_id", sa.Integer(), nullable=True),
            sa.Column("event", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
            sa.Column("zip_code", sa.String(length=10), nullable=True),
            sa.Column("keywords", sa.JSON(), nullable=True),
            sa.Column("result_count", sa.Integer(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["saved_search_id"], ["thrift_radar_saved_searches.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("thrift_radar_logs")

    indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_logs")} if "thrift_radar_logs" in existing_tables else set()
    for name, column in {
        "ix_thrift_radar_logs_created_at": "created_at",
        "ix_thrift_radar_logs_event": "event",
        "ix_thrift_radar_logs_saved_search_id": "saved_search_id",
        "ix_thrift_radar_logs_status": "status",
        "ix_thrift_radar_logs_user_id": "user_id",
        "ix_thrift_radar_logs_zip_code": "zip_code",
    }.items():
        if name not in indexes:
            op.create_index(name, "thrift_radar_logs", [column], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "thrift_radar_logs" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_logs")}
    for name in [
        "ix_thrift_radar_logs_zip_code",
        "ix_thrift_radar_logs_user_id",
        "ix_thrift_radar_logs_status",
        "ix_thrift_radar_logs_saved_search_id",
        "ix_thrift_radar_logs_event",
        "ix_thrift_radar_logs_created_at",
    ]:
        if name in indexes:
            op.drop_index(name, table_name="thrift_radar_logs")
    op.drop_table("thrift_radar_logs")
