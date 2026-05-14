"""add user support ticket visibility flags

Revision ID: 074_support_user_visibility
Revises: 073_ebay_draft_listing_opts
Create Date: 2026-05-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "074_support_user_visibility"
down_revision = "073_ebay_draft_listing_opts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "support_tickets" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("support_tickets")}
    if "user_archived_at" not in columns:
        op.add_column("support_tickets", sa.Column("user_archived_at", sa.DateTime(), nullable=True))
    if "user_deleted_at" not in columns:
        op.add_column("support_tickets", sa.Column("user_deleted_at", sa.DateTime(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("support_tickets")}
    if "ix_support_tickets_user_archived_at" not in indexes:
        op.create_index("ix_support_tickets_user_archived_at", "support_tickets", ["user_archived_at"], unique=False)
    if "ix_support_tickets_user_deleted_at" not in indexes:
        op.create_index("ix_support_tickets_user_deleted_at", "support_tickets", ["user_deleted_at"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "support_tickets" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("support_tickets")}
    if "ix_support_tickets_user_deleted_at" in indexes:
        op.drop_index("ix_support_tickets_user_deleted_at", table_name="support_tickets")
    if "ix_support_tickets_user_archived_at" in indexes:
        op.drop_index("ix_support_tickets_user_archived_at", table_name="support_tickets")

    columns = {column["name"] for column in inspector.get_columns("support_tickets")}
    if "user_deleted_at" in columns:
        op.drop_column("support_tickets", "user_deleted_at")
    if "user_archived_at" in columns:
        op.drop_column("support_tickets", "user_archived_at")
