"""Add unique ebay listing per user

Revision ID: 027_unique_ebay_listing
Revises: 026_add_liberis_loan_tracking
Create Date: 2025-11-05
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '027_unique_ebay_listing'
down_revision = '026_add_liberis_loan_tracking'
branch_labels = None
depends_on = None


def _clear_duplicate_listing_ids():
    """Set duplicate ebay_listing_id to NULL so the unique constraint can be added."""
    conn = op.get_bind()
    # Fetch potential duplicates ordered with most recently updated/created first
    rows = conn.execute(sa.text("""
        SELECT id, user_id, ebay_listing_id, updated_at, created_at
        FROM items
        WHERE ebay_listing_id IS NOT NULL
        ORDER BY user_id, ebay_listing_id, updated_at DESC, created_at DESC, id DESC
    """)).fetchall()

    seen = set()
    duplicates = []

    for row in rows:
        key = (row.user_id, row.ebay_listing_id)
        if key in seen:
            duplicates.append(row.id)
        else:
            seen.add(key)

    for dup_id in duplicates:
        conn.execute(sa.text("UPDATE items SET ebay_listing_id = NULL WHERE id = :id"), {"id": dup_id})


def upgrade():
    _clear_duplicate_listing_ids()
    op.create_unique_constraint(
        'uq_items_user_ebay_listing',
        'items',
        ['user_id', 'ebay_listing_id']
    )


def downgrade():
    op.drop_constraint('uq_items_user_ebay_listing', 'items', type_='unique')
