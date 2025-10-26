"""Add receipt OCR limits and usage tracking

Revision ID: 021
Revises: 020
Create Date: 2025-10-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade():
    # Add OCR limit columns to plan_limits table
    op.add_column('plan_limits', sa.Column('max_receipt_ocr_per_month', sa.Integer(), nullable=True))
    op.add_column('plan_limits', sa.Column('max_receipt_ocr_per_day', sa.Integer(), nullable=True))

    # Create receipt_usage table
    op.create_table(
        'receipt_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('plan_at_time', sa.String(length=50), nullable=False),
        sa.Column('ocr_provider', sa.String(length=50), nullable=True, server_default='openai_vision'),
        sa.Column('estimated_cost', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Add indexes for performance
    op.create_index('ix_receipt_usage_user_id', 'receipt_usage', ['user_id'])
    op.create_index('ix_receipt_usage_processed_at', 'receipt_usage', ['processed_at'])

    # Update existing plan limits with receipt OCR limits
    # This uses raw SQL to set the values
    connection = op.get_bind()

    # Free plan: 1 per day
    connection.execute(sa.text(
        "UPDATE plan_limits SET max_receipt_ocr_per_day = 1, max_receipt_ocr_per_month = NULL WHERE plan = 'free'"
    ))

    # Early adopter: 10 per month
    connection.execute(sa.text(
        "UPDATE plan_limits SET max_receipt_ocr_per_day = NULL, max_receipt_ocr_per_month = 10 WHERE plan = 'early_adopter'"
    ))

    # Premium: 50 per month
    connection.execute(sa.text(
        "UPDATE plan_limits SET max_receipt_ocr_per_day = NULL, max_receipt_ocr_per_month = 50 WHERE plan = 'premium'"
    ))

    # Pro: 200 per month
    connection.execute(sa.text(
        "UPDATE plan_limits SET max_receipt_ocr_per_day = NULL, max_receipt_ocr_per_month = 200 WHERE plan = 'pro'"
    ))

    # God: unlimited
    connection.execute(sa.text(
        "UPDATE plan_limits SET max_receipt_ocr_per_day = NULL, max_receipt_ocr_per_month = NULL WHERE plan = 'god'"
    ))


def downgrade():
    # Drop indexes
    op.drop_index('ix_receipt_usage_processed_at', table_name='receipt_usage')
    op.drop_index('ix_receipt_usage_user_id', table_name='receipt_usage')

    # Drop receipt_usage table
    op.drop_table('receipt_usage')

    # Remove OCR limit columns from plan_limits
    op.drop_column('plan_limits', 'max_receipt_ocr_per_day')
    op.drop_column('plan_limits', 'max_receipt_ocr_per_month')
