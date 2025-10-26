"""Add receipts and receipt_items tables for OCR receipt processing

Revision ID: 020_add_receipts
Revises: 019_add_sold_tracking_to_items
Create Date: 2025-10-25
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '020_add_receipts'
down_revision = '019_add_sold_tracking_to_items'
branch_labels = None
depends_on = None


def upgrade():
    # Create receipts table
    op.create_table(
        'receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=False),
        sa.Column('image_public_id', sa.String(length=255), nullable=False),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('ocr_provider', sa.String(length=50), nullable=True),
        sa.Column('ocr_raw_text', sa.Text(), nullable=True),
        sa.Column('ocr_confidence', sa.Float(), nullable=True),
        sa.Column('ocr_processed_at', sa.DateTime(), nullable=True),
        sa.Column('ocr_error_message', sa.Text(), nullable=True),
        sa.Column('merchant_name', sa.String(length=255), nullable=True),
        sa.Column('receipt_date', sa.Date(), nullable=True),
        sa.Column('receipt_number', sa.String(length=100), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('last_reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_receipts_user_id'), 'receipts', ['user_id'], unique=False)
    op.create_index(op.f('ix_receipts_status'), 'receipts', ['status'], unique=False)
    op.create_index(op.f('ix_receipts_uploaded_at'), 'receipts', ['uploaded_at'], unique=False)

    # Create receipt_items table
    op.create_table(
        'receipt_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('ocr_confidence', sa.Float(), nullable=True),
        sa.Column('user_description', sa.String(length=500), nullable=True),
        sa.Column('user_quantity', sa.Integer(), nullable=True),
        sa.Column('user_unit_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('user_total_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('inventory_item_id', sa.Integer(), nullable=True),
        sa.Column('expense_id', sa.Integer(), nullable=True),
        sa.Column('is_associated', sa.Boolean(), nullable=True),
        sa.Column('is_skipped', sa.Boolean(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('associated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['items.id'], ),
        sa.ForeignKeyConstraint(['expense_id'], ['expenses.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            '(inventory_item_id IS NULL AND expense_id IS NULL) OR '
            '(inventory_item_id IS NOT NULL AND expense_id IS NULL) OR '
            '(inventory_item_id IS NULL AND expense_id IS NOT NULL)',
            name='check_single_association'
        )
    )
    op.create_index(op.f('ix_receipt_items_receipt_id'), 'receipt_items', ['receipt_id'], unique=False)
    op.create_index(op.f('ix_receipt_items_inventory_item_id'), 'receipt_items', ['inventory_item_id'], unique=False)
    op.create_index(op.f('ix_receipt_items_expense_id'), 'receipt_items', ['expense_id'], unique=False)
    op.create_index(op.f('ix_receipt_items_is_associated'), 'receipt_items', ['is_associated'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_receipt_items_is_associated'), table_name='receipt_items')
    op.drop_index(op.f('ix_receipt_items_expense_id'), table_name='receipt_items')
    op.drop_index(op.f('ix_receipt_items_inventory_item_id'), table_name='receipt_items')
    op.drop_index(op.f('ix_receipt_items_receipt_id'), table_name='receipt_items')
    op.drop_table('receipt_items')

    op.drop_index(op.f('ix_receipts_uploaded_at'), table_name='receipts')
    op.drop_index(op.f('ix_receipts_status'), table_name='receipts')
    op.drop_index(op.f('ix_receipts_user_id'), table_name='receipts')
    op.drop_table('receipts')
