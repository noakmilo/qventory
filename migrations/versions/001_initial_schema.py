"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-10-06 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create users table
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)

    # Create settings table
    op.create_table('settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('enable_A', sa.Boolean(), nullable=True),
    sa.Column('enable_B', sa.Boolean(), nullable=True),
    sa.Column('enable_S', sa.Boolean(), nullable=True),
    sa.Column('enable_C', sa.Boolean(), nullable=True),
    sa.Column('label_A', sa.String(), nullable=True),
    sa.Column('label_B', sa.String(), nullable=True),
    sa.Column('label_S', sa.String(), nullable=True),
    sa.Column('label_C', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_settings_user_id'), 'settings', ['user_id'], unique=True)

    # Create subscriptions table
    op.create_table('subscriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('current_period_start', sa.DateTime(), nullable=True),
    sa.Column('current_period_end', sa.DateTime(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('trial_ends_at', sa.DateTime(), nullable=True),
    sa.Column('on_trial', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_subscriptions_plan'), 'subscriptions', ['plan'], unique=False)
    op.create_index(op.f('ix_subscriptions_status'), 'subscriptions', ['status'], unique=False)
    op.create_index(op.f('ix_subscriptions_stripe_customer_id'), 'subscriptions', ['stripe_customer_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_stripe_subscription_id'), 'subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=True)

    # Create plan_limits table
    op.create_table('plan_limits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=50), nullable=False),
    sa.Column('max_items', sa.Integer(), nullable=True),
    sa.Column('max_images_per_item', sa.Integer(), nullable=True),
    sa.Column('max_marketplace_integrations', sa.Integer(), nullable=True),
    sa.Column('can_use_ai_research', sa.Boolean(), nullable=True),
    sa.Column('can_bulk_operations', sa.Boolean(), nullable=True),
    sa.Column('can_export_csv', sa.Boolean(), nullable=True),
    sa.Column('can_import_csv', sa.Boolean(), nullable=True),
    sa.Column('can_use_analytics', sa.Boolean(), nullable=True),
    sa.Column('can_create_listings', sa.Boolean(), nullable=True),
    sa.Column('support_level', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plan')
    )
    op.create_index(op.f('ix_plan_limits_plan'), 'plan_limits', ['plan'], unique=True)

    # Create marketplace_credentials table
    op.create_table('marketplace_credentials',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('marketplace', sa.String(length=50), nullable=False),
    sa.Column('app_id', sa.Text(), nullable=True),
    sa.Column('cert_id', sa.Text(), nullable=True),
    sa.Column('dev_id', sa.Text(), nullable=True),
    sa.Column('access_token', sa.Text(), nullable=True),
    sa.Column('refresh_token', sa.Text(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    sa.Column('ebay_user_id', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(), nullable=True),
    sa.Column('sync_status', sa.String(length=50), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'marketplace', name='unique_user_marketplace')
    )
    op.create_index(op.f('ix_marketplace_credentials_is_active'), 'marketplace_credentials', ['is_active'], unique=False)
    op.create_index(op.f('ix_marketplace_credentials_marketplace'), 'marketplace_credentials', ['marketplace'], unique=False)
    op.create_index(op.f('ix_marketplace_credentials_user_id'), 'marketplace_credentials', ['user_id'], unique=False)

    # Create ai_token_configs table
    op.create_table('ai_token_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('daily_tokens', sa.Integer(), nullable=False),
    sa.Column('display_name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role')
    )

    # Create ai_token_usage table
    op.create_table('ai_token_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('tokens_used', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'date', name='unique_user_date')
    )
    op.create_index(op.f('ix_ai_token_usage_date'), 'ai_token_usage', ['date'], unique=False)

    # Create items table
    op.create_table('items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('upc', sa.String(), nullable=True),
    sa.Column('listing_link', sa.String(), nullable=True),
    sa.Column('web_url', sa.String(), nullable=True),
    sa.Column('ebay_url', sa.String(), nullable=True),
    sa.Column('amazon_url', sa.String(), nullable=True),
    sa.Column('mercari_url', sa.String(), nullable=True),
    sa.Column('vinted_url', sa.String(), nullable=True),
    sa.Column('poshmark_url', sa.String(), nullable=True),
    sa.Column('depop_url', sa.String(), nullable=True),
    sa.Column('whatnot_url', sa.String(), nullable=True),
    sa.Column('A', sa.String(), nullable=True),
    sa.Column('B', sa.String(), nullable=True),
    sa.Column('S', sa.String(), nullable=True),
    sa.Column('C', sa.String(), nullable=True),
    sa.Column('location_code', sa.String(), nullable=True),
    sa.Column('item_thumb', sa.String(), nullable=True),
    sa.Column('image_urls', sa.JSON(), nullable=True),
    sa.Column('supplier', sa.String(), nullable=True),
    sa.Column('item_cost', sa.Float(), nullable=True),
    sa.Column('item_price', sa.Float(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('low_stock_threshold', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('category', sa.String(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('listing_date', sa.Date(), nullable=True),
    sa.Column('purchased_at', sa.Date(), nullable=True),
    sa.Column('ebay_item_id', sa.String(length=100), nullable=True),
    sa.Column('ebay_listing_id', sa.String(length=100), nullable=True),
    sa.Column('ebay_sku', sa.String(length=100), nullable=True),
    sa.Column('synced_from_ebay', sa.Boolean(), nullable=True),
    sa.Column('last_ebay_sync', sa.DateTime(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sku')
    )
    op.create_index(op.f('ix_items_category'), 'items', ['category'], unique=False)
    op.create_index(op.f('ix_items_ebay_item_id'), 'items', ['ebay_item_id'], unique=False)
    op.create_index(op.f('ix_items_ebay_listing_id'), 'items', ['ebay_listing_id'], unique=False)
    op.create_index(op.f('ix_items_is_active'), 'items', ['is_active'], unique=False)
    op.create_index(op.f('ix_items_location_code'), 'items', ['location_code'], unique=False)
    op.create_index(op.f('ix_items_supplier'), 'items', ['supplier'], unique=False)
    op.create_index(op.f('ix_items_upc'), 'items', ['upc'], unique=False)
    op.create_index(op.f('ix_items_user_id'), 'items', ['user_id'], unique=False)

    # Create sales table
    op.create_table('sales',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('marketplace', sa.String(length=50), nullable=False),
    sa.Column('marketplace_order_id', sa.String(length=255), nullable=True),
    sa.Column('item_title', sa.String(), nullable=False),
    sa.Column('item_sku', sa.String(), nullable=True),
    sa.Column('sold_price', sa.Float(), nullable=False),
    sa.Column('item_cost', sa.Float(), nullable=True),
    sa.Column('marketplace_fee', sa.Float(), nullable=True),
    sa.Column('payment_processing_fee', sa.Float(), nullable=True),
    sa.Column('shipping_cost', sa.Float(), nullable=True),
    sa.Column('shipping_charged', sa.Float(), nullable=True),
    sa.Column('other_fees', sa.Float(), nullable=True),
    sa.Column('gross_profit', sa.Float(), nullable=True),
    sa.Column('net_profit', sa.Float(), nullable=True),
    sa.Column('sold_at', sa.DateTime(), nullable=False),
    sa.Column('paid_at', sa.DateTime(), nullable=True),
    sa.Column('shipped_at', sa.DateTime(), nullable=True),
    sa.Column('tracking_number', sa.String(length=255), nullable=True),
    sa.Column('buyer_username', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('return_reason', sa.String(length=255), nullable=True),
    sa.Column('returned_at', sa.DateTime(), nullable=True),
    sa.Column('refund_amount', sa.Float(), nullable=True),
    sa.Column('refund_reason', sa.String(length=255), nullable=True),
    sa.Column('ebay_transaction_id', sa.String(length=100), nullable=True),
    sa.Column('ebay_buyer_username', sa.String(length=100), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sales_ebay_transaction_id'), 'sales', ['ebay_transaction_id'], unique=False)
    op.create_index(op.f('ix_sales_item_id'), 'sales', ['item_id'], unique=False)
    op.create_index(op.f('ix_sales_marketplace'), 'sales', ['marketplace'], unique=False)
    op.create_index(op.f('ix_sales_marketplace_order_id'), 'sales', ['marketplace_order_id'], unique=False)
    op.create_index(op.f('ix_sales_sold_at'), 'sales', ['sold_at'], unique=False)
    op.create_index(op.f('ix_sales_status'), 'sales', ['status'], unique=False)
    op.create_index(op.f('ix_sales_user_id'), 'sales', ['user_id'], unique=False)

    # Create listings table
    op.create_table('listings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('marketplace', sa.String(length=50), nullable=False),
    sa.Column('marketplace_listing_id', sa.String(length=255), nullable=True),
    sa.Column('marketplace_url', sa.String(), nullable=True),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('price', sa.Float(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=True),
    sa.Column('ebay_custom_sku', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('is_synced', sa.Boolean(), nullable=True),
    sa.Column('listed_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(), nullable=True),
    sa.Column('sync_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_item_marketplace_status', 'listings', ['item_id', 'marketplace', 'status'], unique=False)
    op.create_index(op.f('ix_listings_is_synced'), 'listings', ['is_synced'], unique=False)
    op.create_index(op.f('ix_listings_item_id'), 'listings', ['item_id'], unique=False)
    op.create_index(op.f('ix_listings_marketplace'), 'listings', ['marketplace'], unique=False)
    op.create_index(op.f('ix_listings_marketplace_listing_id'), 'listings', ['marketplace_listing_id'], unique=False)
    op.create_index(op.f('ix_listings_status'), 'listings', ['status'], unique=False)
    op.create_index(op.f('ix_listings_user_id'), 'listings', ['user_id'], unique=False)

    # Create reports table
    op.create_table('reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('item_title', sa.String(length=255), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('scraped_count', sa.Integer(), nullable=True),
    sa.Column('result_html', sa.Text(), nullable=True),
    sa.Column('examples_json', sa.Text(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('viewed', sa.Boolean(), nullable=True),
    sa.Column('notified', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('reports')
    op.drop_table('listings')
    op.drop_table('sales')
    op.drop_table('items')
    op.drop_table('ai_token_usage')
    op.drop_table('ai_token_configs')
    op.drop_table('marketplace_credentials')
    op.drop_table('plan_limits')
    op.drop_table('subscriptions')
    op.drop_table('settings')
    op.drop_table('users')
