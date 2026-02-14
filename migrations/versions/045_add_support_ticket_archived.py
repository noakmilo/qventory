"""add support ticket archived flag

Revision ID: 045_add_support_ticket_archived
Revises: 044_add_support_broadcast
Create Date: 2026-02-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "045_add_support_ticket_archived"
down_revision = "044_add_support_broadcast"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("support_tickets") as batch_op:
        batch_op.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.create_index("ix_support_tickets_archived", ["archived"])


def downgrade():
    with op.batch_alter_table("support_tickets") as batch_op:
        batch_op.drop_index("ix_support_tickets_archived")
        batch_op.drop_column("archived")
