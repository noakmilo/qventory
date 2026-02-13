"""add support broadcast fields

Revision ID: 044_add_support_broadcast
Revises: 043_add_sale_ad_fee
Create Date: 2026-02-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "044_add_support_broadcast"
down_revision = "043_add_sale_ad_fee"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("support_tickets") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(length=20), nullable=False, server_default="chat"))
        batch_op.add_column(sa.Column("broadcast_id", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("requires_ack", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_support_tickets_kind", ["kind"])
        batch_op.create_index("ix_support_tickets_broadcast_id", ["broadcast_id"])

    op.execute("UPDATE support_tickets SET kind = 'chat' WHERE kind IS NULL")


def downgrade():
    with op.batch_alter_table("support_tickets") as batch_op:
        batch_op.drop_index("ix_support_tickets_broadcast_id")
        batch_op.drop_index("ix_support_tickets_kind")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("requires_ack")
        batch_op.drop_column("broadcast_id")
        batch_op.drop_column("kind")
