"""Add hidden tasks preferences to settings.

Revision ID: 060_add_hidden_tasks_to_settings
Revises: 059_ref_links
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "060_add_hidden_tasks_to_settings"
down_revision = "059_ref_links"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("hidden_tasks_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("hidden_tasks_json")
