# eBay Import Improvements - Failed Items Tracking & Retry

## Overview

This update adds comprehensive tracking and retry functionality for items that fail to import from eBay. Previously, if an item failed to parse (e.g., due to XML parsing errors, missing fields, or data format issues), it would be silently skipped with only a log entry. Now, these failed items are captured, stored in a database, and can be retried.

## Problem Solved

**Original Issue**: User had 163 items on eBay but only 133 were importing (30 items missing = 18.4% loss rate).

**Root Cause**: Items that failed to parse during import were logged but then skipped with a `continue` statement, causing them to be lost permanently.

**Solution**: Collect failed items, store them with full error details and raw XML data, provide UI to view and retry them.

## Changes Made

### 1. Database Schema

**New Table: `failed_imports`**
- Tracks items that failed to import from eBay
- Stores item identification (eBay ID, title, SKU)
- Captures error details (type, message, traceback)
- Preserves raw XML data for debugging and retry
- Tracks retry attempts and resolution status

**New Migration**: `migrations/versions/007_add_failed_imports_table.py`

**Fields**:
- `id`: Primary key
- `user_id`: Foreign key to users
- `import_job_id`: Foreign key to import_jobs (optional)
- `ebay_listing_id`: eBay item ID
- `ebay_title`: Item title
- `ebay_sku`: Custom SKU field
- `error_type`: Type of error (parsing_error, api_error, etc.)
- `error_message`: Full error message and traceback
- `raw_data`: Raw XML from eBay API (up to 5KB)
- `retry_count`: Number of retry attempts
- `last_retry_at`: Timestamp of last retry
- `resolved`: Boolean flag
- `resolved_at`: Timestamp when resolved
- `created_at`, `updated_at`: Standard timestamps

### 2. Models

**New Model**: `qventory/models/failed_import.py`
- `FailedImport` model with full ORM functionality
- `get_unresolved_for_user(user_id)`: Query helper
- `cleanup_old_resolved(days=90)`: Maintenance helper
- `to_dict()`: JSON serialization

### 3. Import Logic Updates

**File**: `qventory/helpers/ebay_inventory.py`

**Function**: `get_active_listings_trading_api()`
- Added `collect_failures` parameter (default: True)
- Collects failed items during parsing
- Returns tuple `(items, failed_items)` when `collect_failures=True`
- Stores full XML, error message, and traceback for each failure
- Enhanced summary logging shows:
  - Successfully fetched items
  - Failed to parse items
  - Still missing items (eBay reported but not in either category)

**Error Handling**:
```python
except Exception as e:
    # Extract item details even if parsing failed
    failed_id = item_elem.find('ebay:ItemID', ns).text
    failed_title = item_elem.find('ebay:Title', ns).text

    # Collect for retry
    failed_items.append({
        'ebay_listing_id': failed_id,
        'ebay_title': failed_title,
        'error_type': 'parsing_error',
        'error_message': str(e),
        'raw_data': ET.tostring(item_elem, encoding='unicode')[:5000],
        'traceback': traceback.format_exc()[:2000]
    })
```

### 4. Celery Tasks

**File**: `qventory/tasks.py`

**Updated**: `import_ebay_inventory()`
- Now calls Trading API with `collect_failures=True`
- Receives both successful items and failed items
- Stores all failed items in database after import completes
- Avoids duplicates by checking for existing failed imports
- Updates retry count for items that fail repeatedly
- Includes failed items in error_count

**New Task**: `retry_failed_imports(user_id, failed_import_ids=None)`
- Celery task to retry failed imports
- Can retry specific items or all unresolved items
- Parses stored raw XML data
- Attempts to import each item
- Marks as resolved if successful
- Updates retry count and error message if still failing
- Returns summary: retried, resolved, still_failed counts

### 5. Routes

**File**: `qventory/routes/main.py`

**New Routes**:

1. `GET /import/failed` - View failed imports page
   - Displays all unresolved failed imports for current user
   - Shows eBay ID, title, SKU, error type, error message
   - Shows retry count and creation date
   - Provides retry and resolve buttons

2. `POST /api/import/retry` - Retry failed imports
   - Accepts optional list of specific failed_import_ids
   - If none provided, retries all unresolved items
   - Starts background Celery task
   - Returns task_id for tracking

3. `POST /api/import/failed/<id>/resolve` - Mark as manually resolved
   - Allows user to mark item as resolved without retrying
   - Useful for items that will never succeed (e.g., delisted)

### 6. User Interface

**New Template**: `qventory/templates/failed_imports.html`

**Features**:
- Clean table view of all failed imports
- Expandable error details (click to view full error message)
- "Retry All" button to retry all failed items at once
- Individual retry button for each item
- "Mark as resolved" button to dismiss items
- Real-time feedback with loading states
- Auto-refresh after retry operations
- Success state when no failures exist

**Updated Template**: `qventory/templates/dashboard.html`
- Added "Failed Imports" button in toolbar
- Only shown to authenticated users

**Updated Template**: `qventory/templates/base.html`
- Import completion notification now shows failure count
- If failures exist, notification links to Failed Imports page
- Example: "eBay import completed! 133 items processed. (30 failed)"

### 7. Logging Improvements

**Enhanced Summary Output**:
```
============================================================
Trading API Summary:
  eBay reported: 163 total active listings
  Successfully fetched: 133 items
  Failed to parse: 30 items
  ⚠️  30 items failed to parse and will be stored for retry
============================================================
```

**Per-Item Error Logging**:
```
❌ Error parsing item ID=376512069186, Title=Vintage Nike T-Shirt Size L: 'NoneType' object has no attribute 'text'
```

## Usage Workflow

### 1. Normal Import
1. User runs eBay import from `/import/ebay`
2. Import completes with success/failure counts
3. Notification shows: "eBay import completed! 133 items processed. (30 failed)"
4. User clicks "View Failed Items" to see what failed

### 2. View Failed Items
1. Navigate to `/import/failed`
2. See table of all failed imports
3. Each row shows:
   - eBay listing link
   - Title and SKU
   - Error type and message
   - Number of retry attempts
   - Created timestamp

### 3. Retry Failed Items

**Option A: Retry All**
1. Click "Retry All" button
2. Background task processes all failed items
3. Page auto-refreshes after 3 seconds
4. Successfully imported items disappear from list

**Option B: Retry Individual Item**
1. Click retry button (🔄) on specific item
2. Background task processes that single item
3. Page auto-refreshes after 2 seconds

### 4. Mark as Resolved
1. For items that will never succeed (e.g., delisted items)
2. Click resolve button (✓) on item
3. Item is marked as resolved and removed from list
4. Does not delete from database (can be queried later)

## Database Migration

To apply this update:

```bash
# On development
flask db upgrade

# On production (with systemd)
sudo systemctl stop gunicorn-qventory
sudo systemctl stop celery-qventory
cd /var/www/qventory
source venv/bin/activate
flask db upgrade
sudo systemctl start gunicorn-qventory
sudo systemctl start celery-qventory
```

## Monitoring

### Check Failed Imports via SQL
```sql
-- Get count of unresolved failed imports
SELECT user_id, COUNT(*) as failed_count
FROM failed_imports
WHERE resolved = FALSE
GROUP BY user_id;

-- View recent failures
SELECT ebay_listing_id, ebay_title, error_type, error_message, retry_count, created_at
FROM failed_imports
WHERE resolved = FALSE
ORDER BY created_at DESC
LIMIT 20;
```

### Check Logs
```bash
# View import logs
sudo journalctl -u celery-qventory -n 200 --no-pager | grep "EBAY_INVENTORY\|Trading API Summary"

# View retry logs
sudo journalctl -u celery-qventory -n 200 --no-pager | grep "retry"
```

## Maintenance

### Auto-Cleanup (Optional)
The `FailedImport` model includes a cleanup method:

```python
from qventory.models.failed_import import FailedImport

# Delete resolved items older than 90 days
deleted_count = FailedImport.cleanup_old_resolved(days=90)
```

This can be added as a periodic Celery task if desired.

## Benefits

1. **Zero Data Loss**: No items are lost silently anymore
2. **Transparency**: Users can see exactly which items failed and why
3. **Debugging**: Raw XML data is preserved for troubleshooting
4. **Retry Logic**: Failed items can be retried without re-running full import
5. **Tracking**: Retry count and timestamps help identify persistent issues
6. **User Control**: Users can manually resolve items that will never succeed

## Testing Recommendations

1. **Test Failed Import Capture**:
   - Temporarily introduce a parsing error in `get_active_listings_trading_api()`
   - Run import and verify failed items are captured in database

2. **Test Retry Functionality**:
   - Create a failed import record
   - Use retry button to verify it attempts re-import
   - Check logs for retry attempt

3. **Test UI**:
   - View `/import/failed` with no failures (should show success message)
   - View `/import/failed` with failures (should show table)
   - Test "Retry All" button
   - Test individual retry button
   - Test resolve button

4. **Test Notifications**:
   - Run import that produces failures
   - Verify notification shows failure count
   - Verify clicking notification goes to failed imports page

## Future Enhancements

1. **Automatic Retry**: Add periodic Celery task to auto-retry failed imports (e.g., daily)
2. **Email Notifications**: Notify user when items fail to import
3. **Detailed Analytics**: Dashboard widget showing failure trends over time
4. **Error Categorization**: Group failures by error type for easier debugging
5. **Bulk Actions**: Select multiple items and retry/resolve in batch
6. **Export**: Export failed items to CSV for manual review

## API Reference

### FailedImport Model
```python
class FailedImport(db.Model):
    # Create
    failed = FailedImport(
        user_id=1,
        ebay_listing_id='376512069186',
        ebay_title='Vintage Nike T-Shirt',
        error_type='parsing_error',
        error_message='Field missing: CurrentPrice',
        raw_data='<Item>...</Item>'
    )
    db.session.add(failed)
    db.session.commit()

    # Query
    unresolved = FailedImport.get_unresolved_for_user(user_id)

    # Resolve
    failed.resolved = True
    failed.resolved_at = datetime.utcnow()
    db.session.commit()
```

### Celery Tasks
```python
from qventory.tasks import retry_failed_imports

# Retry all unresolved
task = retry_failed_imports.delay(user_id)

# Retry specific items
task = retry_failed_imports.delay(user_id, failed_import_ids=[1, 2, 3])

# Get result
result = task.get()
# {'success': True, 'retried': 30, 'resolved': 28, 'still_failed': 2}
```

## Troubleshooting

**Issue**: Failed imports not showing up
- Check database: `SELECT COUNT(*) FROM failed_imports WHERE resolved = FALSE;`
- Check logs for "Failed to parse" messages
- Verify `collect_failures=True` in Trading API call

**Issue**: Retry fails immediately
- Check if raw_data is NULL (can't retry without XML)
- Check error_message for details
- Try manual import using eBay listing ID

**Issue**: Same items failing repeatedly
- Review error_message to identify root cause
- May indicate eBay API changes or data quality issues
- Consider marking as resolved if unfixable
