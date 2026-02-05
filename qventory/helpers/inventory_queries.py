from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session

PLATFORM_COLUMNS = {
    "web": "web_url",
    "ebay": "ebay_url",
    "amazon": "amazon_url",
    "mercari": "mercari_url",
    "vinted": "vinted_url",
    "poshmark": "poshmark_url",
    "depop": "depop_url",
}


def _rows_to_objects(result: Result) -> List[SimpleNamespace]:
    return [SimpleNamespace(**row) for row in result.mappings().all()]


def _build_item_filters(
    user_id: int,
    *,
    search: Optional[str] = None,
    A: Optional[str] = None,
    B: Optional[str] = None,
    S: Optional[str] = None,
    C: Optional[str] = None,
    platform: Optional[str] = None,
    missing_data: Optional[str] = None,
    alias: str = "i",
) -> Tuple[str, Dict[str, object]]:
    clauses = [f"{alias}.user_id = :user_id"]
    params: Dict[str, object] = {"user_id": user_id}

    if search:
        clauses.append(
            f"({alias}.title ILIKE :search OR {alias}.sku ILIKE :search OR {alias}.supplier ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    if A:
        clauses.append(f'{alias}."A" = :A')
        params["A"] = A
    if B:
        clauses.append(f'{alias}."B" = :B')
        params["B"] = B
    if S:
        clauses.append(f'{alias}."S" = :S')
        params["S"] = S
    if C:
        clauses.append(f'{alias}."C" = :C')
        params["C"] = C

    if platform:
        column = PLATFORM_COLUMNS.get(platform)
        if column:
            clauses.append(f"{alias}.{column} IS NOT NULL")

    if missing_data:
        # Filter items with missing data
        missing_clauses = []
        if missing_data == 'cost':
            missing_clauses.append(f"{alias}.item_cost IS NULL")
        elif missing_data == 'supplier':
            missing_clauses.append(f"({alias}.supplier IS NULL OR {alias}.supplier = '')")
        elif missing_data == 'location':
            missing_clauses.append(f"({alias}.location_code IS NULL OR {alias}.location_code = '')")
        elif missing_data == 'any':
            # Any missing data: cost OR supplier OR location
            missing_clauses.append(f"({alias}.item_cost IS NULL OR {alias}.supplier IS NULL OR {alias}.supplier = '' OR {alias}.location_code IS NULL OR {alias}.location_code = '')")

        if missing_clauses:
            clauses.append(f"({' OR '.join(missing_clauses)})")

    where_clause = " AND ".join(clauses)
    return where_clause, params


ACTIVE_ITEMS_SQL = """
WITH listing_meta AS (
    SELECT
        l.item_id,
        l.user_id,
        MAX(l.listed_at)      AS latest_listed_at,
        MAX(l.last_synced_at) AS latest_synced_at
    FROM listings AS l
    GROUP BY l.item_id, l.user_id
),
normalized AS (
    SELECT
        i.id,
        i.user_id,
        i.title,
        i.sku,
        i.item_thumb,
        i.item_price,
        i.item_cost,
        i.supplier,
        i.location_code,
        i.quantity,
        i.is_active,
        i.inactive_by_user,
        i.web_url,
        i.ebay_url,
        i.amazon_url,
        i.mercari_url,
        i.vinted_url,
        i.poshmark_url,
        i.depop_url,
        i.ebay_listing_id,
        i.listing_date,
        i.created_at,
        i.updated_at,
        i.last_ebay_sync,
        lm.latest_listed_at,
        GREATEST(
            COALESCE(lm.latest_listed_at, '-infinity'::timestamp),
            COALESCE(i.listing_date::timestamp, '-infinity'::timestamp),
            COALESCE(i.created_at, '-infinity'::timestamp)
        ) AS sort_ts
    FROM items AS i
    LEFT JOIN listing_meta AS lm
      ON lm.item_id = i.id
     AND lm.user_id = i.user_id
    WHERE {where_clause}
)
SELECT
    n.*,
    ls.marketplace,
    ls.marketplace_url,
    ls.status AS listing_status,
    ls.listed_at,
    ls.ended_at
FROM normalized AS n
LEFT JOIN LATERAL (
    SELECT l.marketplace,
           l.marketplace_url,
           l.status,
           l.listed_at,
           l.ended_at
    FROM listings AS l
    WHERE l.item_id = n.id
      AND l.user_id = n.user_id
    ORDER BY l.listed_at DESC NULLS LAST, l.created_at DESC NULLS LAST
    LIMIT 1
) AS ls ON TRUE
ORDER BY {order_by}
LIMIT :limit OFFSET :offset;
"""

ACTIVE_COUNT_SQL = """
SELECT COUNT(*)
FROM items AS i
WHERE {where_clause};
"""

SOLD_ITEMS_SQL = """
SELECT
    s.id,
    s.user_id,
    s.item_title AS title,
    s.item_sku AS sku,
    COALESCE(i.item_thumb, NULL) AS item_thumb,
    s.sold_price AS item_price,
    s.sold_price AS sold_price,
    COALESCE(s.item_cost, i.item_cost) AS item_cost,
    s.tax_collected AS tax_collected,
    s.marketplace_fee AS marketplace_fee,
    s.payment_processing_fee AS payment_processing_fee,
    s.shipping_cost AS shipping_cost,
    s.shipping_charged AS shipping_charged,
    s.other_fees AS other_fees,
    s.net_profit AS net_profit,
    COALESCE(i.supplier, NULL) AS supplier,
    COALESCE(i.location_code, NULL) AS location_code,
    COALESCE(i.web_url, NULL) AS web_url,
    COALESCE(i.ebay_url, NULL) AS ebay_url,
    COALESCE(i.amazon_url, NULL) AS amazon_url,
    COALESCE(i.mercari_url, NULL) AS mercari_url,
    COALESCE(i.vinted_url, NULL) AS vinted_url,
    COALESCE(i.poshmark_url, NULL) AS poshmark_url,
    COALESCE(i.depop_url, NULL) AS depop_url,
    COALESCE(i.ebay_listing_id, NULL) AS ebay_listing_id,
    s.sold_at,
    s.shipped_at,
    s.delivered_at,
    s.marketplace,
    s.marketplace_order_id,
    s.status,
    COALESCE(i."A", NULL) AS A,
    COALESCE(i."B", NULL) AS B,
    COALESCE(i."S", NULL) AS S,
    COALESCE(i."C", NULL) AS C
FROM sales AS s
LEFT JOIN items AS i
  ON i.id = s.item_id
 AND i.user_id = s.user_id
WHERE {where_clause}
ORDER BY {order_by}
LIMIT :limit OFFSET :offset;
"""

SOLD_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE {where_clause};
"""

ENDED_ITEMS_SQL = """
SELECT
    i.id,
    i.user_id,
    i.title,
    i.sku,
    i.item_thumb,
    i.item_price,
    i.item_cost,
    i.supplier,
    i.location_code,
    i.web_url,
    i.ebay_url,
    i.amazon_url,
    i.mercari_url,
    i.vinted_url,
    i.poshmark_url,
    i.depop_url,
    i.ebay_listing_id,
    i."A",
    i."B",
    i."S",
    i."C",
    i.updated_at AS ended_ts,
    NULL AS sold_at,
    NULL AS shipped_at,
    NULL AS delivered_at,
    NULL AS marketplace,
    NULL AS marketplace_order_id,
    NULL AS status
FROM items AS i
LEFT JOIN sales AS s
  ON s.item_id = i.id
 AND s.user_id = i.user_id
 AND s.status IN ('paid', 'shipped', 'completed')
WHERE {where_clause}
  AND s.id IS NULL
ORDER BY i.updated_at DESC NULLS LAST, i.id DESC
LIMIT :limit OFFSET :offset;
"""

ENDED_COUNT_SQL = """
SELECT COUNT(*)
FROM items AS i
LEFT JOIN sales AS s
  ON s.item_id = i.id
 AND s.user_id = i.user_id
 AND s.status IN ('paid', 'shipped', 'completed')
WHERE {where_clause}
  AND s.id IS NULL;
"""

# In Transit: Orders that have been shipped but not yet delivered
# Unified fulfillment query - filters by status
FULFILLMENT_ORDERS_SQL = """
SELECT
    s.id,
    s.user_id,
    s.item_id,
    s.marketplace,
    s.marketplace_order_id,
    s.item_title,
    s.item_sku,
    s.buyer_username,
    s.ebay_buyer_username,
    s.carrier,
    s.tracking_number,
    s.sold_price,
    s.shipping_cost,
    s.shipped_at,
    s.delivered_at,
    s.status,
    COALESCE(s.item_title, i.title) AS resolved_title,
    COALESCE(s.item_sku, i.sku)     AS resolved_sku,
    i.item_thumb,
    i.location_code
FROM sales AS s
LEFT JOIN items AS i
  ON i.id = s.item_id
 AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND (:status_filter IS NULL OR s.status = :status_filter)
  AND (:fulfillment_only IS NULL OR (s.shipped_at IS NOT NULL OR s.delivered_at IS NOT NULL))
  AND (:shipped_only IS NULL OR (s.shipped_at IS NOT NULL AND s.delivered_at IS NULL))
  AND (:delivered_only IS NULL OR s.delivered_at IS NOT NULL)
ORDER BY
  CASE
    WHEN s.delivered_at IS NOT NULL THEN s.delivered_at
    WHEN s.shipped_at IS NOT NULL THEN s.shipped_at
    ELSE s.sold_at
  END DESC NULLS LAST,
  s.id DESC
LIMIT :limit OFFSET :offset;
"""

FULFILLMENT_ORDERS_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE s.user_id = :user_id
  AND (:status_filter IS NULL OR s.status = :status_filter)
  AND (:fulfillment_only IS NULL OR (s.shipped_at IS NOT NULL OR s.delivered_at IS NOT NULL))
  AND (:shipped_only IS NULL OR (s.shipped_at IS NOT NULL AND s.delivered_at IS NULL))
  AND (:delivered_only IS NULL OR s.delivered_at IS NOT NULL);
"""

# Legacy queries (kept for backward compatibility, but now use unified approach)
FULFILLMENT_IN_TRANSIT_SQL = FULFILLMENT_ORDERS_SQL
FULFILLMENT_IN_TRANSIT_COUNT_SQL = FULFILLMENT_ORDERS_COUNT_SQL
FULFILLMENT_DELIVERED_SQL = FULFILLMENT_ORDERS_SQL
FULFILLMENT_DELIVERED_COUNT_SQL = FULFILLMENT_ORDERS_COUNT_SQL

THUMBNAIL_MISMATCH_SQL = """
WITH thumbs AS (
    SELECT
        i.id,
        i.user_id,
        i.title,
        i.item_thumb,
        right(i.item_thumb, NULLIF(strpos(reverse(i.item_thumb), '/') - 1, -1)) AS thumb_slug
    FROM items AS i
    WHERE i.user_id = :user_id
      AND i.item_thumb IS NOT NULL
),
duplicates AS (
    SELECT thumb_slug
    FROM thumbs
    GROUP BY thumb_slug
    HAVING COUNT(*) > 1
)
SELECT thumb_slug,
       ARRAY_AGG(id ORDER BY id)    AS item_ids,
       ARRAY_AGG(title ORDER BY id) AS titles
FROM thumbs
WHERE thumb_slug IN (SELECT thumb_slug FROM duplicates)
GROUP BY thumb_slug;
"""

SALE_TITLE_MISMATCH_SQL = """
SELECT s.id AS sale_id,
       s.item_id,
       s.item_title AS sale_title,
       i.title      AS current_title
FROM sales AS s
JOIN items AS i
  ON i.id = s.item_id
 AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND s.item_id IS NOT NULL
  AND s.item_title IS DISTINCT FROM i.title
LIMIT 100;
"""


def fetch_active_items(
    session: Session,
    *,
    user_id: int,
    search: Optional[str] = None,
    A: Optional[str] = None,
    B: Optional[str] = None,
    S: Optional[str] = None,
    C: Optional[str] = None,
    platform: Optional[str] = None,
    missing_data: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    where_clause, params = _build_item_filters(
        user_id,
        search=search,
        A=A,
        B=B,
        S=S,
        C=C,
        platform=platform,
        missing_data=missing_data,
    )
    where_clause = (
        f"{where_clause} AND i.is_active IS TRUE AND COALESCE(i.inactive_by_user, FALSE) = FALSE"
    )

    order_map = {
        "title": "n.title",
        "sku": "n.sku",
        "supplier": "n.supplier",
        "cost": "n.item_cost",
        "price": "n.item_price",
        "location": "n.location_code",
        "listed_at": "n.sort_ts",
        "updated_at": "n.updated_at",
    }
    direction = "ASC" if (sort_dir or "").lower() == "asc" else "DESC"
    order_col = order_map.get((sort_by or "").lower(), "n.sort_ts")
    order_by = f"{order_col} {direction} NULLS LAST, n.id DESC"

    query_sql = ACTIVE_ITEMS_SQL.format(where_clause=where_clause, order_by=order_by)
    count_sql = ACTIVE_COUNT_SQL.format(where_clause=where_clause)

    query_params = dict(params)
    query_params.update({"limit": limit, "offset": offset})

    items = _rows_to_objects(session.execute(text(query_sql), query_params))
    total = session.execute(text(count_sql), params).scalar_one()
    return items, total


def fetch_inactive_by_user_items(
    session: Session,
    *,
    user_id: int,
    search: Optional[str] = None,
    A: Optional[str] = None,
    B: Optional[str] = None,
    S: Optional[str] = None,
    C: Optional[str] = None,
    platform: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    where_clause, params = _build_item_filters(
        user_id,
        search=search,
        A=A,
        B=B,
        S=S,
        C=C,
        platform=platform,
        missing_data=None,
    )
    where_clause = (
        f"{where_clause} AND i.is_active IS TRUE AND COALESCE(i.inactive_by_user, FALSE) = TRUE"
    )

    order_map = {
        "title": "n.title",
        "sku": "n.sku",
        "supplier": "n.supplier",
        "cost": "n.item_cost",
        "price": "n.item_price",
        "location": "n.location_code",
        "listed_at": "n.sort_ts",
        "updated_at": "n.updated_at",
    }
    direction = "ASC" if (sort_dir or "").lower() == "asc" else "DESC"
    order_col = order_map.get((sort_by or "").lower(), "n.sort_ts")
    order_by = f"{order_col} {direction} NULLS LAST, n.id DESC"

    query_sql = ACTIVE_ITEMS_SQL.format(where_clause=where_clause, order_by=order_by)
    count_sql = ACTIVE_COUNT_SQL.format(where_clause=where_clause)

    query_params = dict(params)
    query_params.update({"limit": limit, "offset": offset})

    items = _rows_to_objects(session.execute(text(query_sql), query_params))
    total = session.execute(text(count_sql), params).scalar_one()
    return items, total


def fetch_sold_items(
    session: Session,
    *,
    user_id: int,
    search: Optional[str] = None,
    A: Optional[str] = None,
    B: Optional[str] = None,
    S: Optional[str] = None,
    C: Optional[str] = None,
    platform: Optional[str] = None,
    missing_data: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """
    Fetch sold items (sales records) for a user.
    NOTE: This returns SALES, not items from inventory.
    """
    clauses = ["s.user_id = :user_id", "s.status IN ('paid','shipped','completed')"]
    params: Dict[str, object] = {"user_id": user_id}

    if search:
        clauses.append(
            "(s.item_title ILIKE :search OR s.item_sku ILIKE :search OR i.supplier ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where_clause = " AND ".join(clauses)
    order_map = {
        "title": "s.item_title",
        "sku": "s.item_sku",
        "supplier": "i.supplier",
        "cost": "COALESCE(s.item_cost, i.item_cost)",
        "sold_price": "s.sold_price",
        "net_profit": "s.net_profit",
        "sold_at": "s.sold_at",
        "location": "i.location_code",
    }
    direction = "ASC" if (sort_dir or "").lower() == "asc" else "DESC"
    order_col = order_map.get((sort_by or "").lower(), "s.sold_at")
    order_by = f"{order_col} {direction} NULLS LAST, s.id DESC"

    query_sql = SOLD_ITEMS_SQL.format(where_clause=where_clause, order_by=order_by)
    count_sql = SOLD_COUNT_SQL.format(where_clause=where_clause)

    query_params = dict(params)
    query_params.update({"limit": limit, "offset": offset})

    items = _rows_to_objects(session.execute(text(query_sql), query_params))
    total = session.execute(text(count_sql), params).scalar_one()
    return items, total


def fetch_ended_items(
    session: Session,
    *,
    user_id: int,
    search: Optional[str] = None,
    A: Optional[str] = None,
    B: Optional[str] = None,
    S: Optional[str] = None,
    C: Optional[str] = None,
    platform: Optional[str] = None,
    missing_data: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    where_clause, params = _build_item_filters(
        user_id,
        search=search,
        A=A,
        B=B,
        S=S,
        C=C,
        platform=platform,
        missing_data=missing_data,
    )
    where_clause = f"{where_clause} AND COALESCE(i.is_active, FALSE) = FALSE"

    query_sql = ENDED_ITEMS_SQL.format(where_clause=where_clause)
    count_sql = ENDED_COUNT_SQL.format(where_clause=where_clause)

    query_params = dict(params)
    query_params.update({"limit": limit, "offset": offset})

    items = _rows_to_objects(session.execute(text(query_sql), query_params))
    total = session.execute(text(count_sql), params).scalar_one()
    return items, total


def fetch_fulfillment_orders(
    session: Session,
    *,
    user_id: int,
    status_filter: Optional[str] = None,
    fulfillment_only: bool = False,
    shipped_only: bool = False,
    delivered_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """
    Unified fulfillment query - fetch orders with flexible filtering

    Args:
        session: Database session
        user_id: User ID to filter by
        status_filter: Filter by specific status ('shipped', 'delivered', 'completed', etc.)
        shipped_only: If True, only show shipped but not delivered (in transit)
        delivered_only: If True, only show delivered orders
        limit: Max results to return
        offset: Pagination offset

    Returns:
        Tuple of (orders list, total count)
    """
    query_params = {
        "user_id": user_id,
        "status_filter": status_filter,
        "fulfillment_only": True if fulfillment_only else None,
        "shipped_only": True if shipped_only else None,
        "delivered_only": True if delivered_only else None,
        "limit": limit,
        "offset": offset
    }

    items = _rows_to_objects(session.execute(text(FULFILLMENT_ORDERS_SQL), query_params))

    count_params = {
        "user_id": user_id,
        "status_filter": status_filter,
        "fulfillment_only": True if fulfillment_only else None,
        "shipped_only": True if shipped_only else None,
        "delivered_only": True if delivered_only else None
    }
    total = session.execute(text(FULFILLMENT_ORDERS_COUNT_SQL), count_params).scalar_one()

    return items, total


def fetch_fulfillment_in_transit(
    session: Session,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """Fetch orders that are shipped but not yet delivered (LEGACY - uses unified query)"""
    return fetch_fulfillment_orders(
        session,
        user_id=user_id,
        shipped_only=True,
        limit=limit,
        offset=offset
    )


def fetch_fulfillment_delivered(
    session: Session,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """Fetch orders that have been delivered (LEGACY - uses unified query)"""
    return fetch_fulfillment_orders(
        session,
        user_id=user_id,
        delivered_only=True,
        limit=limit,
        offset=offset
    )


def detect_thumbnail_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(THUMBNAIL_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)


def detect_sale_title_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(SALE_TITLE_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)
