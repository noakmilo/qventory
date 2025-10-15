"""add auto_relist_rules and auto_relist_history tables

Revision ID: 008_add_auto_relist_tables
Revises: 007_add_failed_imports_table
Create Date: 2025-10-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_add_auto_relist_tables'
down_revision = '007_add_failed_imports_table'
branch_labels = None
depends_on = '007_inventory_indexes'  # Merge both 007 branches


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Create auto_relist_rules table
    table_name = 'auto_relist_rules'
    if table_name not in existing_tables:
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),

            # eBay identifiers
            sa.Column('offer_id', sa.String(length=100), nullable=False),
            sa.Column('sku', sa.String(length=100), nullable=True),
            sa.Column('inventory_item_id', sa.String(length=100), nullable=True),
            sa.Column('marketplace_id', sa.String(length=50), nullable=True),

            # Display info
            sa.Column('item_title', sa.String(length=500), nullable=True),
            sa.Column('current_price', sa.Float(), nullable=True),
            sa.Column('listing_id', sa.String(length=100), nullable=True),

            # Mode
            sa.Column('mode', sa.String(length=20), nullable=False),

            # Auto mode settings
            sa.Column('frequency', sa.String(length=20), nullable=True),
            sa.Column('custom_interval_days', sa.Integer(), nullable=True),
            sa.Column('quiet_hours_start', sa.Time(), nullable=True),
            sa.Column('quiet_hours_end', sa.Time(), nullable=True),
            sa.Column('timezone', sa.String(length=50), nullable=True),

            # Safety rules
            sa.Column('min_hours_since_last_order', sa.Integer(), nullable=True),
            sa.Column('check_active_returns', sa.Boolean(), nullable=True),
            sa.Column('require_positive_quantity', sa.Boolean(), nullable=True),
            sa.Column('check_duplicate_skus', sa.Boolean(), nullable=True),
            sa.Column('pause_on_error', sa.Boolean(), nullable=True),
            sa.Column('max_consecutive_errors', sa.Integer(), nullable=True),

            # Manual mode settings
            sa.Column('pending_changes', sa.JSON(), nullable=True),
            sa.Column('apply_changes', sa.Boolean(), nullable=True),
            sa.Column('manual_trigger_requested', sa.Boolean(), nullable=True),

            # Common settings
            sa.Column('withdraw_publish_delay_seconds', sa.Integer(), nullable=True),

            # Status & tracking
            sa.Column('enabled', sa.Boolean(), nullable=True),
            sa.Column('next_run_at', sa.DateTime(), nullable=True),
            sa.Column('last_run_at', sa.DateTime(), nullable=True),
            sa.Column('last_run_status', sa.String(length=50), nullable=True),
            sa.Column('last_error_message', sa.Text(), nullable=True),
            sa.Column('last_new_listing_id', sa.String(length=100), nullable=True),

            # Counters
            sa.Column('run_count', sa.Integer(), nullable=True),
            sa.Column('success_count', sa.Integer(), nullable=True),
            sa.Column('error_count', sa.Integer(), nullable=True),
            sa.Column('consecutive_errors', sa.Integer(), nullable=True),

            # Metadata
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),

            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )

        # Create indexes for auto_relist_rules
        op.create_index('idx_auto_relist_user_id', table_name, ['user_id'])
        op.create_index('idx_auto_relist_offer_id', table_name, ['offer_id'])
        op.create_index('idx_auto_relist_sku', table_name, ['sku'])
        op.create_index('idx_auto_relist_mode', table_name, ['mode'])
        op.create_index('idx_auto_relist_enabled', table_name, ['enabled'])
        op.create_index('idx_auto_relist_next_run', table_name, ['next_run_at'])
        op.create_index('idx_auto_relist_created', table_name, ['created_at'])
        op.create_index('idx_auto_relist_user_enabled', table_name, ['user_id', 'enabled'])

    # Create auto_relist_history table
    table_name = 'auto_relist_history'
    if table_name not in existing_tables:
        op.create_table(
            table_name,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('rule_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),

            # Execution timing
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('duration_seconds', sa.Integer(), nullable=True),

            # Execution context
            sa.Column('mode', sa.String(length=20), nullable=True),
            sa.Column('changes_applied', sa.JSON(), nullable=True),

            # Results
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('old_listing_id', sa.String(length=100), nullable=True),
            sa.Column('new_listing_id', sa.String(length=100), nullable=True),

            # Pricing changes
            sa.Column('old_price', sa.Float(), nullable=True),
            sa.Column('new_price', sa.Float(), nullable=True),

            # Error tracking
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('error_code', sa.String(length=50), nullable=True),
            sa.Column('skip_reason', sa.String(length=500), nullable=True),

            # Raw API responses
            sa.Column('withdraw_response', sa.JSON(), nullable=True),
            sa.Column('update_response', sa.JSON(), nullable=True),
            sa.Column('publish_response', sa.JSON(), nullable=True),

            sa.ForeignKeyConstraint(['rule_id'], ['auto_relist_rules.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id')
        )

        # Create indexes for auto_relist_history
        op.create_index('idx_auto_relist_history_rule_id', table_name, ['rule_id'])
        op.create_index('idx_auto_relist_history_user_id', table_name, ['user_id'])
        op.create_index('idx_auto_relist_history_started', table_name, ['started_at'])
        op.create_index('idx_auto_relist_history_status', table_name, ['status'])
        op.create_index('idx_auto_relist_history_user_date', table_name, ['user_id', 'started_at'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop auto_relist_history table
    if 'auto_relist_history' in existing_tables:
        op.drop_table('auto_relist_history')

    # Drop auto_relist_rules table
    if 'auto_relist_rules' in existing_tables:
        op.drop_table('auto_relist_rules')
