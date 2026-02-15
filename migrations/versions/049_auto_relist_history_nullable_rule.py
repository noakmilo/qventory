"""make auto_relist_history rule_id nullable

Revision ID: 049_auto_relist_rule_nullable
Revises: 048_profit_calc
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "049_auto_relist_rule_nullable"
down_revision = "048_profit_calc"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("auto_relist_history") as batch_op:
        batch_op.alter_column(
            "rule_id",
            existing_type=sa.Integer(),
            nullable=True
        )


def downgrade():
    with op.batch_alter_table("auto_relist_history") as batch_op:
        batch_op.alter_column(
            "rule_id",
            existing_type=sa.Integer(),
            nullable=False
        )
