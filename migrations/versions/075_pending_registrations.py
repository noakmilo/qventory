"""add pending registrations

Revision ID: 075_pending_registrations
Revises: 074_support_user_visibility
Create Date: 2026-05-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "075_pending_registrations"
down_revision = "074_support_user_visibility"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pending_registrations" in inspector.get_table_names():
        return

    op.create_table(
        "pending_registrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ref_source", sa.String(length=64), nullable=True),
        sa.Column("ref_medium", sa.String(length=64), nullable=True),
        sa.Column("ref_campaign", sa.String(length=128), nullable=True),
        sa.Column("ref_content", sa.String(length=128), nullable=True),
        sa.Column("ref_term", sa.String(length=128), nullable=True),
        sa.Column("ref_landing_path", sa.String(length=255), nullable=True),
        sa.Column("ref_first_touch_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_registrations_email"), "pending_registrations", ["email"], unique=True)
    op.create_index(op.f("ix_pending_registrations_username"), "pending_registrations", ["username"], unique=True)
    op.create_index(op.f("ix_pending_registrations_ref_source"), "pending_registrations", ["ref_source"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pending_registrations" not in inspector.get_table_names():
        return

    op.drop_index(op.f("ix_pending_registrations_ref_source"), table_name="pending_registrations")
    op.drop_index(op.f("ix_pending_registrations_username"), table_name="pending_registrations")
    op.drop_index(op.f("ix_pending_registrations_email"), table_name="pending_registrations")
    op.drop_table("pending_registrations")
