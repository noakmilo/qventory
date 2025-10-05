# Database Migration Guide

## Overview
This guide explains how to run the database migration to add API integrations and subscription features to Qventory.

## What This Migration Does

### New Tables Created:
1. **sales** - Track real sales across marketplaces with profit calculations
2. **marketplace_credentials** - Store encrypted API credentials for eBay, Mercari, Depop, Whatnot
3. **listings** - Track active listings across multiple marketplaces
4. **subscriptions** - User subscription management (free/pro/premium)
5. **plan_limits** - Feature limits for each subscription tier

### Items Table Updates:
- `description` - Full item description
- `upc` - Universal Product Code
- `whatnot_url` - Whatnot marketplace link
- `image_urls` - JSON array of multiple images
- `quantity` - Stock quantity
- `low_stock_threshold` - Alert threshold
- `is_active` - Active/inactive flag
- `category` - Item category
- `tags` - JSON array of tags
- `purchased_at` - Purchase date
- `notes` - Additional notes
- `updated_at` - Last update timestamp

### Default Plan Limits Inserted:
- **Free**: 50 items max, 1 image per item, no marketplace integrations
- **Pro**: Unlimited items, 5 images per item, 2 marketplace integrations, AI research, analytics
- **Premium**: Unlimited items, 10 images per item, 10 marketplace integrations, all features

## Prerequisites

1. **Install cryptography package:**
   ```bash
   pip install cryptography==43.0.3
   ```

2. **Generate encryption key** (for API credentials):
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Add to .env file:**
   ```
   ENCRYPTION_KEY=<key_from_step_2>
   ```

## Running the Migration

### On Production Server:

```bash
# SSH into your server
ssh your-server

# Navigate to project directory
cd /path/to/qventory

# Activate virtual environment if using one
source venv/bin/activate

# Run migration
python3 run_migration.py
```

### On Local Development:

```bash
# Make sure you're in the project root
cd /Users/kmilonoa/Documents/GitHub/qventory

# Run migration
python3 run_migration.py
```

### Custom Migration File:

```bash
python3 run_migration.py path/to/custom_migration.sql
```

## Migration Script Features

✅ **Transaction-based** - All changes are committed together or rolled back on error
✅ **Idempotent** - Safe to run multiple times (skips existing tables/columns)
✅ **Progress tracking** - Shows each SQL statement as it executes
✅ **Error handling** - Automatically rolls back on failure

## Post-Migration Steps

1. **Restart your application:**
   ```bash
   sudo systemctl restart qventory
   ```

2. **Verify tables were created:**
   ```bash
   sqlite3 /path/to/app.db ".tables"
   ```
   You should see: `sales`, `marketplace_credentials`, `listings`, `subscriptions`, `plan_limits`

3. **Check existing users have subscriptions:**
   ```bash
   sqlite3 /path/to/app.db "SELECT COUNT(*) FROM subscriptions;"
   ```
   Should match your user count.

4. **Verify plan limits:**
   ```bash
   sqlite3 /path/to/app.db "SELECT plan, max_items, can_use_ai_research FROM plan_limits;"
   ```

## Using the New Features

### Check User Plan:
```python
from flask_login import current_user

# Get current plan
plan = current_user.plan_name  # "Free", "Pro", or "Premium"

# Check if premium
if current_user.is_premium:
    print("User has premium features")
```

### Feature Gates:
```python
# Check specific features
if current_user.can_use_feature('ai_research'):
    # Allow AI research
    pass

if current_user.can_use_feature('analytics'):
    # Show analytics dashboard
    pass

# Check item limits
if not current_user.can_add_items(5):
    flash("You've reached your item limit. Upgrade to add more!")
    return redirect(url_for('upgrade'))

remaining = current_user.items_remaining()  # Returns int or None (unlimited)
```

### Add Marketplace Credentials:
```python
from qventory.models import MarketplaceCredential

cred = MarketplaceCredential(
    user_id=current_user.id,
    marketplace='ebay'
)
cred.set_access_token('secret_token_here')  # Automatically encrypted
db.session.add(cred)
db.session.commit()

# Later, retrieve:
token = cred.get_access_token()  # Automatically decrypted
```

### Track Sales:
```python
from qventory.models import Sale
from datetime import datetime

sale = Sale(
    user_id=current_user.id,
    item_id=item.id,
    marketplace='ebay',
    item_title=item.title,
    item_sku=item.sku,
    sold_price=49.99,
    item_cost=20.00,
    marketplace_fee=4.99,
    payment_processing_fee=1.45,
    shipping_cost=5.00,
    shipped_charged=8.00,
    sold_at=datetime.utcnow(),
    status='completed'
)
sale.calculate_profit()  # Auto-calculates gross_profit and net_profit
db.session.add(sale)
db.session.commit()
```

## Rollback (If Needed)

If something goes wrong and you need to rollback:

```sql
-- Remove new tables
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS marketplace_credentials;
DROP TABLE IF EXISTS listings;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS plan_limits;

-- Remove new columns from items (SQLite doesn't support DROP COLUMN easily)
-- You would need to:
-- 1. Rename items table
-- 2. Create new items table with old schema
-- 3. Copy data back
-- 4. Drop renamed table
```

**Note:** SQLite doesn't support dropping columns easily. It's safer to keep the migration and fix forward rather than rollback.

## Troubleshooting

### "unable to open database file"
- Check DATABASE_URI in .env points to correct path
- Ensure directory exists and has write permissions
- Verify you're running from correct directory

### "ENCRYPTION_KEY not found"
- Make sure you added ENCRYPTION_KEY to .env
- Restart application after adding to .env

### "Table already exists"
- Migration is idempotent - this warning is normal
- Script will skip existing tables automatically

### "Column already exists"
- Migration is idempotent - this is expected behavior
- Script continues safely

## Next Steps

After migration, you should implement:

1. **Subscription management UI** - Allow users to upgrade/downgrade
2. **Sales tracking interface** - Mark items as sold, view profit
3. **Analytics dashboard** - Show revenue, profit trends
4. **Marketplace integrations** - Connect eBay, Mercari APIs when approved
5. **Feature gates in UI** - Show upgrade prompts for premium features

## Support

If you encounter issues:
1. Check application logs
2. Verify database permissions
3. Ensure all dependencies installed
4. Check .env configuration

For production issues, always backup your database before running migrations:
```bash
cp /path/to/app.db /path/to/app.db.backup.$(date +%Y%m%d_%H%M%S)
```
