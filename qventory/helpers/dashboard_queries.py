"""
Dashboard queries for home page statistics and recent activity
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from types import SimpleNamespace
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session


def _rows_to_objects(result: Result) -> List[SimpleNamespace]:
    """Convert SQLAlchemy result rows to SimpleNamespace objects"""
    return [SimpleNamespace(**row) for row in result.mappings().all()]


# ==================== STATS QUERIES (30 DAYS) ====================

STATS_30_DAYS_SQL = """
WITH date_range AS (
    SELECT
        NOW() - INTERVAL '30 days' AS start_date,
        NOW() AS end_date,
        NOW() - INTERVAL '60 days' AS prev_start_date,
        NOW() - INTERVAL '30 days' AS prev_end_date
),
current_period AS (
    SELECT
        COUNT(DISTINCT s.id) AS sales_count,
        COALESCE(SUM(s.sold_price), 0) AS total_revenue,
        COUNT(DISTINCT CASE WHEN s.shipped_at IS NOT NULL THEN s.id END) AS shipped_count,
        COUNT(DISTINCT CASE WHEN s.delivered_at IS NOT NULL THEN s.id END) AS delivered_count
    FROM sales AS s
    CROSS JOIN date_range AS dr
    WHERE s.user_id = :user_id
      AND s.sold_at >= dr.start_date
      AND s.sold_at <= dr.end_date
      AND s.status IN ('paid', 'shipped', 'completed')
),
previous_period AS (
    SELECT
        COUNT(DISTINCT s.id) AS sales_count,
        COALESCE(SUM(s.sold_price), 0) AS total_revenue,
        COUNT(DISTINCT CASE WHEN s.shipped_at IS NOT NULL THEN s.id END) AS shipped_count,
        COUNT(DISTINCT CASE WHEN s.delivered_at IS NOT NULL THEN s.id END) AS delivered_count
    FROM sales AS s
    CROSS JOIN date_range AS dr
    WHERE s.user_id = :user_id
      AND s.sold_at >= dr.prev_start_date
      AND s.sold_at < dr.prev_end_date
      AND s.status IN ('paid', 'shipped', 'completed')
)
SELECT
    cp.sales_count,
    cp.total_revenue,
    cp.shipped_count,
    cp.delivered_count,
    CASE
        WHEN pp.sales_count = 0 THEN NULL
        ELSE ROUND(((cp.sales_count::numeric - pp.sales_count::numeric) / pp.sales_count::numeric) * 100, 1)
    END AS sales_change_pct,
    CASE
        WHEN pp.total_revenue = 0 THEN NULL
        ELSE ROUND(((cp.total_revenue - pp.total_revenue) / pp.total_revenue) * 100, 1)
    END AS revenue_change_pct,
    CASE
        WHEN pp.shipped_count = 0 THEN NULL
        ELSE ROUND(((cp.shipped_count::numeric - pp.shipped_count::numeric) / pp.shipped_count::numeric) * 100, 1)
    END AS shipped_change_pct,
    CASE
        WHEN pp.delivered_count = 0 THEN NULL
        ELSE ROUND(((cp.delivered_count::numeric - pp.delivered_count::numeric) / pp.delivered_count::numeric) * 100, 1)
    END AS delivered_change_pct
FROM current_period AS cp
CROSS JOIN previous_period AS pp;
"""


# ==================== RECENT SALES (Last 5) ====================

RECENT_SALES_SQL = """
SELECT
    s.id,
    s.item_id,
    s.item_title,
    s.item_sku,
    s.sold_price,
    s.sold_at,
    s.shipped_at,
    s.delivered_at,
    s.status,
    s.marketplace,
    i.item_thumb,
    i.title AS current_title,
    CASE
        WHEN s.delivered_at IS NOT NULL THEN 'delivered'
        WHEN s.shipped_at IS NOT NULL THEN 'shipped'
        ELSE 'awaiting_ship'
    END AS fulfillment_status
FROM sales AS s
LEFT JOIN items AS i ON i.id = s.item_id AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND s.status IN ('paid', 'shipped', 'completed')
ORDER BY s.sold_at DESC NULLS LAST
LIMIT :limit;
"""


# ==================== RECENTLY LISTED (Last 5) ====================

RECENT_LISTED_SQL = """
WITH listing_dates AS (
    SELECT
        i.id,
        i.user_id,
        i.title,
        i.sku,
        i.item_price,
        i.item_thumb,
        i.ebay_url,
        i.web_url,
        GREATEST(
            COALESCE(MAX(l.listed_at), '-infinity'::timestamp),
            COALESCE(i.listing_date::timestamp, '-infinity'::timestamp),
            COALESCE(i.last_ebay_sync, '-infinity'::timestamp),
            COALESCE(i.created_at, '-infinity'::timestamp)
        ) AS listed_at
    FROM items AS i
    LEFT JOIN listings AS l ON l.item_id = i.id AND l.user_id = i.user_id
    WHERE i.user_id = :user_id
      AND i.is_active = TRUE
    GROUP BY i.id, i.user_id, i.title, i.sku, i.item_price, i.item_thumb,
             i.ebay_url, i.web_url, i.listing_date, i.last_ebay_sync, i.created_at
)
SELECT
    ld.id,
    ld.title,
    ld.sku,
    ld.item_price,
    ld.item_thumb,
    ld.listed_at,
    ld.ebay_url,
    ld.web_url
FROM listing_dates AS ld
ORDER BY ld.listed_at DESC NULLS LAST
LIMIT :limit;
"""


# ==================== RECENTLY SOLD ITEMS (Last 5) ====================

RECENT_SOLD_ITEMS_SQL = """
WITH sold_items AS (
    SELECT
        s.item_id,
        MAX(s.sold_at) AS last_sold_at,
        MAX(s.sold_price) AS last_sold_price,
        COUNT(*) AS sale_count
    FROM sales AS s
    WHERE s.user_id = :user_id
      AND s.item_id IS NOT NULL
      AND s.status IN ('paid', 'shipped', 'completed')
    GROUP BY s.item_id
)
SELECT
    i.id,
    i.title,
    i.sku,
    i.item_thumb,
    i.ebay_url,
    i.web_url,
    si.last_sold_at,
    si.last_sold_price,
    si.sale_count
FROM sold_items AS si
JOIN items AS i ON i.id = si.item_id
WHERE i.user_id = :user_id
ORDER BY si.last_sold_at DESC NULLS LAST
LIMIT :limit;
"""


# ==================== RECENT FULFILLMENT (Last 10) ====================

RECENT_FULFILLMENT_SQL = """
SELECT
    s.id,
    s.item_id,
    s.item_title,
    s.item_sku,
    s.sold_price,
    s.shipped_at,
    s.delivered_at,
    s.carrier,
    s.tracking_number,
    s.marketplace,
    s.status,
    i.item_thumb,
    CASE
        WHEN s.delivered_at IS NOT NULL THEN 'delivered'
        WHEN s.shipped_at IS NOT NULL THEN 'shipped'
        ELSE 'pending'
    END AS fulfillment_status,
    GREATEST(
        COALESCE(s.delivered_at, '-infinity'::timestamp),
        COALESCE(s.shipped_at, '-infinity'::timestamp)
    ) AS event_ts
FROM sales AS s
LEFT JOIN items AS i ON i.id = s.item_id AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND (s.shipped_at IS NOT NULL OR s.delivered_at IS NOT NULL)
ORDER BY event_ts DESC NULLS LAST
LIMIT :limit;
"""


# ==================== PENDING TASKS ====================

PENDING_TASKS_SQL = """
SELECT
    (SELECT COUNT(*) FROM items WHERE user_id = :user_id AND item_cost IS NULL) AS items_missing_cost,
    (SELECT COUNT(*) FROM items WHERE user_id = :user_id AND supplier IS NULL) AS items_missing_supplier,
    (SELECT COUNT(*) FROM ebay_tokens WHERE user_id = :user_id AND access_token IS NOT NULL) AS ebay_connected
;
"""


# ==================== QUERY FUNCTIONS ====================

def fetch_dashboard_stats(session: Session, *, user_id: int) -> SimpleNamespace:
    """Fetch 30-day stats with percentage changes"""
    result = session.execute(text(STATS_30_DAYS_SQL), {"user_id": user_id})
    rows = _rows_to_objects(result)
    return rows[0] if rows else SimpleNamespace(
        sales_count=0,
        total_revenue=0,
        shipped_count=0,
        delivered_count=0,
        sales_change_pct=None,
        revenue_change_pct=None,
        shipped_change_pct=None,
        delivered_change_pct=None
    )


def fetch_recent_sales(session: Session, *, user_id: int, limit: int = 5) -> List[SimpleNamespace]:
    """Fetch recent sales with fulfillment status"""
    result = session.execute(text(RECENT_SALES_SQL), {"user_id": user_id, "limit": limit})
    return _rows_to_objects(result)


def fetch_recently_listed(session: Session, *, user_id: int, limit: int = 5) -> List[SimpleNamespace]:
    """Fetch recently listed active items"""
    result = session.execute(text(RECENT_LISTED_SQL), {"user_id": user_id, "limit": limit})
    return _rows_to_objects(result)


def fetch_recently_sold_items(session: Session, *, user_id: int, limit: int = 5) -> List[SimpleNamespace]:
    """Fetch recently sold items (unique items, not individual sales)"""
    result = session.execute(text(RECENT_SOLD_ITEMS_SQL), {"user_id": user_id, "limit": limit})
    return _rows_to_objects(result)


def fetch_recent_fulfillment(session: Session, *, user_id: int, limit: int = 10) -> List[SimpleNamespace]:
    """Fetch recent shipped/delivered orders"""
    result = session.execute(text(RECENT_FULFILLMENT_SQL), {"user_id": user_id, "limit": limit})
    return _rows_to_objects(result)


def fetch_pending_tasks(session: Session, *, user_id: int) -> SimpleNamespace:
    """Fetch pending tasks count"""
    result = session.execute(text(PENDING_TASKS_SQL), {"user_id": user_id})
    rows = _rows_to_objects(result)
    return rows[0] if rows else SimpleNamespace(
        items_missing_cost=0,
        items_missing_supplier=0,
        ebay_connected=0
    )
