"""add ebay finance cache tables

Revision ID: 030_add_ebay_finance_cache
Revises: 029_sys_settings
Create Date: 2026-01-06 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '030_add_ebay_finance_cache'
down_revision = '029_sys_settings'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'ebay_payouts' not in existing_tables:
        op.create_table(
            'ebay_payouts',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('external_id', sa.String(length=64), nullable=False),
            sa.Column('payout_id', sa.String(length=64), nullable=True),
            sa.Column('payout_date', sa.DateTime(), nullable=True),
            sa.Column('status', sa.String(length=40), nullable=True),
            sa.Column('gross_amount', sa.Numeric(12, 2), nullable=True),
            sa.Column('fee_amount', sa.Numeric(12, 2), nullable=True),
            sa.Column('net_amount', sa.Numeric(12, 2), nullable=True),
            sa.Column('currency', sa.String(length=10), nullable=True),
            sa.Column('raw_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'external_id', name='uq_ebay_payouts_user_external')
        )

    payout_indexes = {idx['name'] for idx in inspector.get_indexes('ebay_payouts')} if 'ebay_payouts' in existing_tables else set()
    if 'idx_ebay_payouts_user_date' not in payout_indexes:
        op.create_index('idx_ebay_payouts_user_date', 'ebay_payouts', ['user_id', 'payout_date'])

    if 'ebay_finance_transactions' not in existing_tables:
        op.create_table(
            'ebay_finance_transactions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('external_id', sa.String(length=64), nullable=False),
            sa.Column('transaction_id', sa.String(length=64), nullable=True),
            sa.Column('transaction_date', sa.DateTime(), nullable=True),
            sa.Column('transaction_type', sa.String(length=40), nullable=True),
            sa.Column('amount', sa.Numeric(12, 2), nullable=True),
            sa.Column('currency', sa.String(length=10), nullable=True),
            sa.Column('order_id', sa.String(length=64), nullable=True),
            sa.Column('reference_id', sa.String(length=64), nullable=True),
            sa.Column('raw_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'external_id', name='uq_ebay_fin_tx_user_external')
        )

    tx_indexes = {idx['name'] for idx in inspector.get_indexes('ebay_finance_transactions')} if 'ebay_finance_transactions' in existing_tables else set()
    if 'idx_ebay_fin_tx_user_date' not in tx_indexes:
        op.create_index('idx_ebay_fin_tx_user_date', 'ebay_finance_transactions', ['user_id', 'transaction_date'])


def downgrade():
    op.drop_index('idx_ebay_fin_tx_user_date', table_name='ebay_finance_transactions')
    op.drop_table('ebay_finance_transactions')
    op.drop_index('idx_ebay_payouts_user_date', table_name='ebay_payouts')
    op.drop_table('ebay_payouts')
