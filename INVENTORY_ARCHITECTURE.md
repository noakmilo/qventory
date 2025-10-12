# Qventory Inventory Architecture

## Overview

Qventory now properly separates inventory into three distinct views, each serving a different purpose:

1. **Active Inventory** - Current items available for sale
2. **Sold Items** - Historical sales transactions
3. **Ended Items** - Inactive items that were never sold

## 1. Active Inventory (`/inventory/active`)

**Purpose**: Show current inventory items that are actively listed for sale.

**Data Source**: `items` table

**Key Criteria**:
- `is_active = TRUE`
- Includes items with `quantity > 0`
- Shows latest listing information via JOIN to `listings` table

**User Actions**:
- ✅ Full editing capabilities (title, price, cost, supplier, location, etc.)
- ✅ Bulk actions (sync to eBay, delete)
- ✅ AI Research, Profit Calculator
- ✅ Print labels, generate QR codes
- ✅ Sync location to eBay Custom SKU

**Query Logic**:
```sql
FROM items AS i
WHERE i.user_id = :user_id
  AND i.is_active IS TRUE
  AND [filters: search, A, B, S, C, platform]
```

## 2. Sold Items (`/inventory/sold`)

**Purpose**: Show historical sales transactions (completed orders).

**Data Source**: `sales` table (primary) with LEFT JOIN to `items` table

**Key Criteria**:
- `status IN ('paid', 'shipped', 'completed')`
- Shows ALL sales, even if original item no longer exists in inventory
- Title/SKU/cost come from `sales` table (snapshot at time of sale)
- Thumbnail/URLs come from `items` table if item still exists

**User Actions**:
- ✅ View Profit Calculator (read-only, but cost is editable for profit tracking)
- ✅ View eBay listing link
- ❌ NO bulk actions (historical data)
- ❌ NO editing of title, supplier, location (read-only fields)
- ❌ NO delete (use dedicated sales management if needed)

**Important Design Decision**:
The `item_cost` field in sales is ALWAYS editable, even for sold items. This allows users to:
- Add missing cost information later
- Correct cost data for accurate profit calculations
- Update cost if they remembered wrong at time of sale

**Query Logic**:
```sql
SELECT
    s.id,
    s.item_title AS title,
    s.item_sku AS sku,
    s.sold_price AS item_price,
    s.item_cost,
    s.sold_at,
    s.shipped_at,
    s.marketplace,
    s.status,
    COALESCE(i.item_thumb, NULL) AS item_thumb,
    COALESCE(i.supplier, NULL) AS supplier,
    COALESCE(i.location_code, NULL) AS location_code
FROM sales AS s
LEFT JOIN items AS i ON i.id = s.item_id AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND s.status IN ('paid','shipped','completed')
ORDER BY s.sold_at DESC
```

**Why LEFT JOIN?**
- Shows ALL sales, even if the item was deleted from inventory
- If item still exists, we get supplementary data (thumbnail, supplier)
- If item was deleted, we still show the sale with data from the sales record

## 3. Ended Items (`/inventory/ended`)

**Purpose**: Show items that were listed but terminated/ended without selling.

**Data Source**: `items` table with LEFT JOIN to `sales` table

**Key Criteria**:
- `is_active = FALSE`
- Has NO completed sales (`s.id IS NULL`)
- Item was listed but ended early (eBay EndItem, manual deactivation, expired, etc.)

**User Actions**:
- ✅ Full editing capabilities (can reactivate, modify, delete)
- ✅ Bulk actions available
- ✅ Can relist item or delete

**eBay Context**:
According to eBay API documentation, listings can end for many reasons:
- `EndedWithSales` - Normal completion with sale
- `Sold` - Buy It Now purchase
- `NotAvailable` - Seller ended early
- `Incorrect` - Seller error
- `LostOrBroken` - Item damaged
- `OtherListingError` - Various issues
- `SellToHighBidder` - Auction ended early
- `Scheduled` - Scheduled end date

**Query Logic**:
```sql
SELECT i.*
FROM items AS i
LEFT JOIN sales AS s
  ON s.item_id = i.id
 AND s.user_id = i.user_id
 AND s.status IN ('paid', 'shipped', 'completed')
WHERE i.user_id = :user_id
  AND COALESCE(i.is_active, FALSE) = FALSE
  AND s.id IS NULL  -- No completed sales
  AND [filters: search, A, B, S, C, platform]
ORDER BY i.updated_at DESC
```

**Why the JOIN?**
- We need to exclude items that were sold (those go to "Sold Items" view)
- Only show items that ended without a completed sale
- `s.id IS NULL` ensures no completed sale exists for this item

## Data Flow Example

### Scenario 1: Item Listed and Sold
1. Create item → appears in **Active Inventory**
2. List on eBay → `ebay_url` populated, still in **Active Inventory**
3. Item sells → sale record created, item `is_active = FALSE`
4. Result: Item now appears in **Sold Items** (from `sales` table)

### Scenario 2: Item Listed but Ended Early
1. Create item → appears in **Active Inventory**
2. List on eBay → `ebay_url` populated, still in **Active Inventory**
3. End listing early → item `is_active = FALSE`, no sale created
4. Result: Item now appears in **Ended Items** (from `items` table)

### Scenario 3: Item Deleted After Sale
1. Item sells → appears in **Sold Items**
2. User deletes item from inventory → item removed from `items` table
3. Result: Sale still appears in **Sold Items** (LEFT JOIN allows this)

## Filtering Support

| Filter | Active | Sold | Ended |
|--------|--------|------|-------|
| Search (title/SKU) | ✅ | ❌ | ✅ |
| Category A/B/S/C | ✅ | ❌ | ✅ |
| Platform (eBay, Amazon, etc.) | ✅ | ❌ | ✅ |

**Why no filters on Sold Items?**
- Sold items are purely historical transactions
- Search/filter should be done before sale (in Active/Ended views)
- Future enhancement: Add search on sold items if needed for reporting

## Template Behavior

The `_item_row.html` template conditionally renders based on `view_type`:

```jinja
{% if view_type == 'sold' %}
  {# Read-only rendering #}
  <span class="tag">{{ it.supplier }}</span>
{% else %}
  {# Editable inline-edit component #}
  <div class="inline-edit" data-field="supplier">
    ...
  </div>
{% endif %}
```

**Fields by View Type**:

| Field | Active | Sold | Ended |
|-------|--------|------|-------|
| Thumbnail | Read-only | Read-only | Read-only |
| Title | Read-only | Read-only | Read-only |
| SKU | Read-only | Read-only | Read-only |
| Supplier | ✏️ Editable | Read-only | ✏️ Editable |
| Cost | ✏️ Editable | ✏️ Editable | ✏️ Editable |
| Price | Read-only | Read-only | Read-only |
| Location | ✏️ Editable | Read-only | ✏️ Editable |
| Checkbox | ✅ Enabled | ❌ Disabled | ✅ Enabled |

## Import Behavior

### eBay Import Modes

1. **New Only** - Skip items that already exist (matches by eBay listing ID or SKU)
2. **Update Existing** - Update matching items, skip new ones
3. **Sync All** (Default) - Import new items AND update existing ones

### Sales Import

When importing eBay orders:
- Creates records in `sales` table
- Attempts to match to existing `item_id` using multiple strategies:
  1. eBay Listing ID
  2. eBay Custom SKU
  3. Qventory SKU
  4. Exact title match
  5. Fuzzy title match (80% similarity)
- If no match found, creates sale with `item_id = NULL`
- Use "Re-Match Sales to Items" button to retry matching later

## Database Relationships

```
┌─────────────────┐
│     items       │
│  (inventory)    │
├─────────────────┤
│ id (PK)         │
│ user_id         │
│ title           │
│ sku             │
│ is_active       │
│ quantity        │
│ item_price      │
│ item_cost       │
│ ebay_listing_id │
└────────┬────────┘
         │
         │ 1:N
         │
         ▼
┌─────────────────┐
│     sales       │
│  (transactions) │
├─────────────────┤
│ id (PK)         │
│ user_id         │
│ item_id (FK)    │  ← Can be NULL for unmatched sales
│ item_title      │  ← Snapshot at sale time
│ item_sku        │  ← Snapshot at sale time
│ sold_price      │
│ item_cost       │
│ sold_at         │
│ shipped_at      │
│ marketplace     │
│ status          │
└─────────────────┘
```

## Celery Background Tasks

### `import_ebay_inventory`
- Fetches active eBay listings via `GetSellerList` API
- Creates/updates items in `items` table
- Updates `is_active`, `ebay_listing_id`, `ebay_url`, etc.

### `import_ebay_orders`
- Fetches eBay orders via `GetOrders` API
- Creates records in `sales` table
- Attempts to match sales to items
- Updates item quantity when matched

### `rematch_sales_to_items`
- Re-attempts matching for sales with `item_id = NULL`
- Uses 5 matching strategies
- Updates `item_id` when match found
- Logs unmatched sales for manual review

## Summary

This architecture ensures:
1. ✅ Clear separation between current inventory and historical transactions
2. ✅ Sold items remain accessible even if inventory item is deleted
3. ✅ Ended items are tracked separately from sold items
4. ✅ Proper read-only enforcement for historical data
5. ✅ Flexible filtering for active and ended inventory
6. ✅ Cost is always editable for accurate profit tracking
