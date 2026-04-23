"""add ebay offer id column to items

Revision ID: 064_add_item_offer_id
Revises: 063_harden_free_plan_limits_lock
Create Date: 2026-04-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '064_add_item_offer_id'
down_revision = '063_harden_free_plan_limits_lock'
branch_labels = None
depends_on = None


ITEMS_TABLE = 'items'
OFFER_ID_COLUMN = 'ebay_offer_id'
OFFER_ID_INDEX = 'ix_items_ebay_offer_id'


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if ITEMS_TABLE not in table_names:
        return

    columns = {column.get('name') for column in inspector.get_columns(ITEMS_TABLE)}
    if OFFER_ID_COLUMN not in columns:
        op.add_column(ITEMS_TABLE, sa.Column(OFFER_ID_COLUMN, sa.String(length=128), nullable=True))

    index_names = {index.get('name') for index in inspector.get_indexes(ITEMS_TABLE)}
    if OFFER_ID_INDEX not in index_names:
        op.create_index(OFFER_ID_INDEX, ITEMS_TABLE, [OFFER_ID_COLUMN], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if ITEMS_TABLE not in table_names:
        return

    index_names = {index.get('name') for index in inspector.get_indexes(ITEMS_TABLE)}
    if OFFER_ID_INDEX in index_names:
        op.drop_index(OFFER_ID_INDEX, table_name=ITEMS_TABLE)

    columns = {column.get('name') for column in inspector.get_columns(ITEMS_TABLE)}
    if OFFER_ID_COLUMN in columns:
        op.drop_column(ITEMS_TABLE, OFFER_ID_COLUMN)
