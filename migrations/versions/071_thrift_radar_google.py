"""add thrift radar google keywords and routes

Revision ID: 071_thrift_radar_google
Revises: 070_thrift_radar_logs
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "071_thrift_radar_google"
down_revision = "070_thrift_radar_logs"
branch_labels = None
depends_on = None


DEFAULT_KEYWORDS = [
    {
        "slug": "thrift_store",
        "label": "Thrift Stores",
        "keywords": [
            "thrift store",
            "thrift shop",
            "trift store",
            "trift shop",
            "thrift",
            "second hand store",
            "consignment store",
            "goodwill",
            "goodwill store",
            "goodwill outlet",
            "savers thrift",
            "savers",
            "value village",
            "salvation army thrift",
            "out of the closet",
            "st vincent de paul thrift",
        ],
        "match_type": "any",
        "fallback_icon": "fa-shirt",
        "color": "#22c55e",
        "display_order": 10,
    },
    {
        "slug": "flea_market",
        "label": "Flea Markets",
        "keywords": ["flea market", "swap meet", "antique market"],
        "match_type": "any",
        "fallback_icon": "fa-shop",
        "color": "#f97316",
        "display_order": 20,
    },
    {
        "slug": "outlet",
        "label": "Outlets",
        "keywords": ["outlet store", "clearance outlet", "liquidation outlet"],
        "match_type": "any",
        "fallback_icon": "fa-bag-shopping",
        "color": "#8b5cf6",
        "display_order": 30,
    },
]


def _has_column(inspector, table_name, column_name):
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "thrift_radar_saved_searches" in existing_tables:
        for column in [
            sa.Column("search_mode", sa.String(length=20), nullable=False, server_default="zip"),
            sa.Column("city", sa.String(length=120), nullable=True),
            sa.Column("state", sa.String(length=80), nullable=True),
            sa.Column("center_lat", sa.Float(), nullable=True),
            sa.Column("center_lng", sa.Float(), nullable=True),
            sa.Column("radius_meters", sa.Integer(), nullable=False, server_default="40233"),
        ]:
            if not _has_column(inspector, "thrift_radar_saved_searches", column.name):
                op.add_column("thrift_radar_saved_searches", column)
        op.alter_column("thrift_radar_saved_searches", "zip_code", existing_type=sa.String(length=10), nullable=True)
        indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_saved_searches")}
        if "ix_thrift_radar_saved_searches_search_mode" not in indexes:
            op.create_index("ix_thrift_radar_saved_searches_search_mode", "thrift_radar_saved_searches", ["search_mode"], unique=False)

    if "thrift_radar_keywords" not in existing_tables:
        op.create_table(
            "thrift_radar_keywords",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("keywords", sa.JSON(), nullable=False),
            sa.Column("match_type", sa.String(length=12), nullable=False, server_default="any"),
            sa.Column("icon_url", sa.String(length=1000), nullable=True),
            sa.Column("fallback_icon", sa.String(length=80), nullable=True),
            sa.Column("color", sa.String(length=20), nullable=False, server_default="#22c55e"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_thrift_radar_keywords_slug"),
        )
        op.create_index("ix_thrift_radar_keywords_slug", "thrift_radar_keywords", ["slug"], unique=True)
        op.create_index("ix_thrift_radar_keywords_is_active", "thrift_radar_keywords", ["is_active"], unique=False)
        op.bulk_insert(sa.table(
            "thrift_radar_keywords",
            sa.column("slug", sa.String),
            sa.column("label", sa.String),
            sa.column("keywords", sa.JSON),
            sa.column("match_type", sa.String),
            sa.column("fallback_icon", sa.String),
            sa.column("color", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("display_order", sa.Integer),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        ), [{**row, "is_active": True} for row in DEFAULT_KEYWORDS])

    if "thrift_radar_saved_routes" not in existing_tables:
        op.create_table(
            "thrift_radar_saved_routes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("saved_search_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="driving"),
            sa.Column("origin", sa.JSON(), nullable=True),
            sa.Column("stops", sa.JSON(), nullable=False),
            sa.Column("route_data", sa.JSON(), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["saved_search_id"], ["thrift_radar_saved_searches.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_thrift_radar_saved_routes_user_id", "thrift_radar_saved_routes", ["user_id"], unique=False)
        op.create_index("ix_thrift_radar_saved_routes_saved_search_id", "thrift_radar_saved_routes", ["saved_search_id"], unique=False)
        op.create_index("ix_thrift_radar_saved_routes_is_archived", "thrift_radar_saved_routes", ["is_archived"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "thrift_radar_saved_routes" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_saved_routes")}
        for name in [
            "ix_thrift_radar_saved_routes_is_archived",
            "ix_thrift_radar_saved_routes_saved_search_id",
            "ix_thrift_radar_saved_routes_user_id",
        ]:
            if name in indexes:
                op.drop_index(name, table_name="thrift_radar_saved_routes")
        op.drop_table("thrift_radar_saved_routes")

    if "thrift_radar_keywords" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_keywords")}
        for name in ["ix_thrift_radar_keywords_is_active", "ix_thrift_radar_keywords_slug"]:
            if name in indexes:
                op.drop_index(name, table_name="thrift_radar_keywords")
        op.drop_table("thrift_radar_keywords")

    if "thrift_radar_saved_searches" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("thrift_radar_saved_searches")}
        if "ix_thrift_radar_saved_searches_search_mode" in indexes:
            op.drop_index("ix_thrift_radar_saved_searches_search_mode", table_name="thrift_radar_saved_searches")
        for col in ["radius_meters", "center_lng", "center_lat", "state", "city", "search_mode"]:
            if _has_column(inspector, "thrift_radar_saved_searches", col):
                op.drop_column("thrift_radar_saved_searches", col)
        op.alter_column("thrift_radar_saved_searches", "zip_code", existing_type=sa.String(length=10), nullable=False)
