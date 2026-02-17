"""add feedback response_source

Revision ID: 056_feedback_response_source
Revises: 055_feedback_manager
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "056_feedback_response_source"
down_revision = "055_feedback_manager"
branch_labels = None
depends_on = None


def _column_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    cols = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in cols


def upgrade():
    bind = op.get_bind()
    if not _column_exists(bind, "ebay_feedback", "response_source"):
        op.add_column("ebay_feedback", sa.Column("response_source", sa.String(length=20)))


def downgrade():
    op.drop_column("ebay_feedback", "response_source")
