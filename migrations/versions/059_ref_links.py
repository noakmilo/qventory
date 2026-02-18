"""Add referral tracking for ref links.

Revision ID: 059_ref_links
Revises: 058_ai_token_scenarios
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "059_ref_links"
down_revision = "058_ai_token_scenarios"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "referral_visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("utm_source", sa.String(length=64), nullable=True),
        sa.Column("utm_medium", sa.String(length=64), nullable=True),
        sa.Column("utm_campaign", sa.String(length=128), nullable=True),
        sa.Column("utm_content", sa.String(length=128), nullable=True),
        sa.Column("utm_term", sa.String(length=128), nullable=True),
        sa.Column("landing_path", sa.String(length=255), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_referral_visits_utm_source", "referral_visits", ["utm_source"])
    op.create_index("ix_referral_visits_session_id", "referral_visits", ["session_id"])

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("ref_source", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("ref_medium", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("ref_campaign", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("ref_content", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("ref_term", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("ref_landing_path", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("ref_first_touch_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_users_ref_source", ["ref_source"])


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_ref_source")
        batch_op.drop_column("ref_first_touch_at")
        batch_op.drop_column("ref_landing_path")
        batch_op.drop_column("ref_term")
        batch_op.drop_column("ref_content")
        batch_op.drop_column("ref_campaign")
        batch_op.drop_column("ref_medium")
        batch_op.drop_column("ref_source")

    op.drop_table("referral_visits")
