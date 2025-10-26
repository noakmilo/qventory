"""Fix receipt_usage foreign key to use CASCADE delete

Revision ID: 022_fix_receipt_usage_cascade
Revises: 021_add_receipt_ocr_limits
Create Date: 2025-10-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '022_fix_receipt_usage_cascade'
down_revision = '021_add_receipt_ocr_limits'
branch_labels = None
depends_on = None


def upgrade():
    """
    Update foreign keys in receipt_usage table to use CASCADE on delete.
    This fixes the error when deleting receipts that have usage records.
    """

    # For PostgreSQL, we need to drop and recreate the foreign key constraints
    # with ON DELETE CASCADE

    with op.batch_alter_table('receipt_usage', schema=None) as batch_op:
        # Drop existing foreign key constraints
        batch_op.drop_constraint('receipt_usage_receipt_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('receipt_usage_user_id_fkey', type_='foreignkey')

        # Recreate with CASCADE
        batch_op.create_foreign_key(
            'receipt_usage_receipt_id_fkey',
            'receipts',
            ['receipt_id'],
            ['id'],
            ondelete='CASCADE'
        )
        batch_op.create_foreign_key(
            'receipt_usage_user_id_fkey',
            'users',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade():
    """
    Revert foreign keys to not use CASCADE (original state)
    """

    with op.batch_alter_table('receipt_usage', schema=None) as batch_op:
        # Drop CASCADE constraints
        batch_op.drop_constraint('receipt_usage_receipt_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('receipt_usage_user_id_fkey', type_='foreignkey')

        # Recreate without CASCADE
        batch_op.create_foreign_key(
            'receipt_usage_receipt_id_fkey',
            'receipts',
            ['receipt_id'],
            ['id']
        )
        batch_op.create_foreign_key(
            'receipt_usage_user_id_fkey',
            'users',
            ['user_id'],
            ['id']
        )
