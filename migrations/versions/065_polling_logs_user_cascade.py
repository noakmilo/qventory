"""add cascade delete to polling logs user foreign key

Revision ID: 065_polling_logs_user_cascade
Revises: 064_add_item_offer_id
Create Date: 2026-05-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "065_polling_logs_user_cascade"
down_revision = "064_add_item_offer_id"
branch_labels = None
depends_on = None


TABLE_NAME = "polling_logs"
REFERENT_TABLE = "users"
COLUMN_NAME = "user_id"
CONSTRAINT_NAME = "polling_logs_user_id_fkey"


def _find_user_fk(inspector):
    for fk in inspector.get_foreign_keys(TABLE_NAME):
        constrained = fk.get("constrained_columns") or []
        referred_table = fk.get("referred_table")
        referred_columns = fk.get("referred_columns") or []
        if constrained == [COLUMN_NAME] and referred_table == REFERENT_TABLE and referred_columns == ["id"]:
            return fk.get("name")
    return None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    fk_name = _find_user_fk(inspector)
    if fk_name:
        op.drop_constraint(fk_name, TABLE_NAME, type_="foreignkey")

    op.create_foreign_key(
        CONSTRAINT_NAME,
        TABLE_NAME,
        REFERENT_TABLE,
        [COLUMN_NAME],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        return

    fk_name = _find_user_fk(inspector)
    if fk_name:
        op.drop_constraint(fk_name, TABLE_NAME, type_="foreignkey")

    op.create_foreign_key(
        CONSTRAINT_NAME,
        TABLE_NAME,
        REFERENT_TABLE,
        [COLUMN_NAME],
        ["id"],
    )
