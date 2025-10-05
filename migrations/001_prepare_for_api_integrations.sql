-- Migration: Prepare database for API integrations and freemium model
-- Date: 2025-01-XX
-- Description: Add tables for sales tracking, marketplace integrations, and subscriptions

-- ====================
-- 1. SALES TABLE
-- ====================
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_id INTEGER,

    -- Sale info
    marketplace VARCHAR(50) NOT NULL,
    marketplace_order_id VARCHAR(255),

    -- Item snapshot
    item_title TEXT NOT NULL,
    item_sku VARCHAR(255),

    -- Pricing
    sold_price REAL NOT NULL,
    item_cost REAL,

    -- Fees
    marketplace_fee REAL DEFAULT 0,
    payment_processing_fee REAL DEFAULT 0,
    shipping_cost REAL DEFAULT 0,
    shipping_charged REAL DEFAULT 0,
    other_fees REAL DEFAULT 0,

    -- Calculated profit
    gross_profit REAL,
    net_profit REAL,

    -- Dates
    sold_at DATETIME NOT NULL,
    paid_at DATETIME,
    shipped_at DATETIME,

    -- Tracking
    tracking_number VARCHAR(255),
    buyer_username VARCHAR(255),

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',

    -- Metadata
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_user_id ON sales(user_id);
CREATE INDEX IF NOT EXISTS idx_sales_item_id ON sales(item_id);
CREATE INDEX IF NOT EXISTS idx_sales_marketplace ON sales(marketplace);
CREATE INDEX IF NOT EXISTS idx_sales_marketplace_order_id ON sales(marketplace_order_id);
CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);

-- ====================
-- 2. MARKETPLACE CREDENTIALS TABLE
-- ====================
CREATE TABLE IF NOT EXISTS marketplace_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,

    -- Marketplace
    marketplace VARCHAR(50) NOT NULL,

    -- Encrypted credentials
    app_id TEXT,
    cert_id TEXT,
    dev_id TEXT,

    -- Encrypted OAuth tokens
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at DATETIME,

    -- Status
    is_active BOOLEAN DEFAULT 1,
    last_synced_at DATETIME,
    sync_status VARCHAR(50),
    error_message TEXT,

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, marketplace)
);

CREATE INDEX IF NOT EXISTS idx_marketplace_credentials_user_id ON marketplace_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_marketplace_credentials_marketplace ON marketplace_credentials(marketplace);
CREATE INDEX IF NOT EXISTS idx_marketplace_credentials_active ON marketplace_credentials(is_active);

-- ====================
-- 3. LISTINGS TABLE
-- ====================
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,

    -- Marketplace info
    marketplace VARCHAR(50) NOT NULL,
    marketplace_listing_id VARCHAR(255),
    marketplace_url TEXT,

    -- Listing details
    title TEXT,
    description TEXT,
    price REAL,
    quantity INTEGER DEFAULT 1,

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    is_synced BOOLEAN DEFAULT 0,

    -- Dates
    listed_at DATETIME,
    ended_at DATETIME,
    last_synced_at DATETIME,

    -- Sync info
    sync_error TEXT,

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id);
CREATE INDEX IF NOT EXISTS idx_listings_item_id ON listings(item_id);
CREATE INDEX IF NOT EXISTS idx_listings_marketplace ON listings(marketplace);
CREATE INDEX IF NOT EXISTS idx_listings_marketplace_listing_id ON listings(marketplace_listing_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_synced ON listings(is_synced);
CREATE INDEX IF NOT EXISTS idx_listings_item_marketplace_status ON listings(item_id, marketplace, status);

-- ====================
-- 4. SUBSCRIPTIONS TABLE
-- ====================
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,

    -- Plan
    plan VARCHAR(50) NOT NULL DEFAULT 'free',
    status VARCHAR(50) NOT NULL DEFAULT 'active',

    -- Dates
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_period_start DATETIME,
    current_period_end DATETIME,
    cancelled_at DATETIME,
    ended_at DATETIME,

    -- Stripe/Payment (future)
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    -- Trial
    trial_ends_at DATETIME,
    on_trial BOOLEAN DEFAULT 0,

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON subscriptions(plan);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer_id ON subscriptions(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_subscription_id ON subscriptions(stripe_subscription_id);

-- ====================
-- 5. PLAN LIMITS TABLE
-- ====================
CREATE TABLE IF NOT EXISTS plan_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan VARCHAR(50) NOT NULL UNIQUE,

    -- Limits
    max_items INTEGER,
    max_images_per_item INTEGER DEFAULT 1,
    max_marketplace_integrations INTEGER DEFAULT 0,

    -- Features
    can_use_ai_research BOOLEAN DEFAULT 0,
    can_bulk_operations BOOLEAN DEFAULT 0,
    can_export_csv BOOLEAN DEFAULT 1,
    can_import_csv BOOLEAN DEFAULT 1,
    can_use_analytics BOOLEAN DEFAULT 0,
    can_create_listings BOOLEAN DEFAULT 0,

    -- Support
    support_level VARCHAR(50) DEFAULT 'community',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Insert default plan limits
INSERT OR IGNORE INTO plan_limits (
    plan, max_items, max_images_per_item, max_marketplace_integrations,
    can_use_ai_research, can_bulk_operations, can_use_analytics, can_create_listings,
    support_level
) VALUES
    ('free', 50, 1, 0, 0, 0, 0, 0, 'community'),
    ('pro', NULL, 5, 2, 1, 1, 1, 1, 'email'),
    ('premium', NULL, 10, 10, 1, 1, 1, 1, 'priority');

-- ====================
-- 6. UPDATE ITEMS TABLE
-- ====================
-- Add new columns to items table
ALTER TABLE items ADD COLUMN description TEXT;
ALTER TABLE items ADD COLUMN upc VARCHAR(255);
ALTER TABLE items ADD COLUMN whatnot_url TEXT;
ALTER TABLE items ADD COLUMN image_urls TEXT;  -- JSON array
ALTER TABLE items ADD COLUMN quantity INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE items ADD COLUMN low_stock_threshold INTEGER DEFAULT 1;
ALTER TABLE items ADD COLUMN is_active BOOLEAN DEFAULT 1;
ALTER TABLE items ADD COLUMN category VARCHAR(255);
ALTER TABLE items ADD COLUMN tags TEXT;  -- JSON array
ALTER TABLE items ADD COLUMN purchased_at DATE;
ALTER TABLE items ADD COLUMN notes TEXT;
ALTER TABLE items ADD COLUMN updated_at DATETIME;

-- Create indices for new columns
CREATE INDEX IF NOT EXISTS idx_items_upc ON items(upc);
CREATE INDEX IF NOT EXISTS idx_items_supplier ON items(supplier);
CREATE INDEX IF NOT EXISTS idx_items_is_active ON items(is_active);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);

-- ====================
-- 7. CREATE DEFAULT SUBSCRIPTIONS FOR EXISTING USERS
-- ====================
INSERT INTO subscriptions (user_id, plan, status, started_at)
SELECT id, 'free', 'active', CURRENT_TIMESTAMP
FROM users
WHERE id NOT IN (SELECT user_id FROM subscriptions);
