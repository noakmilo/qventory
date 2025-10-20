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
        clauses.append(f"({alias}.title ILIKE :search OR {alias}.sku ILIKE :search)")
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
        lm.latest_synced_at,
        GREATEST(
            COALESCE(lm.latest_listed_at, '-infinity'::timestamp),
            COALESCE(lm.latest_synced_at, '-infinity'::timestamp),
            COALESCE(i.listing_date::timestamp, '-infinity'::timestamp),
            COALESCE(i.last_ebay_sync, '-infinity'::timestamp),
            COALESCE(i.updated_at, '-infinity'::timestamp),
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
ORDER BY n.sort_ts DESC NULLS LAST, n.id DESC
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
    s.item_cost,
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
    NULL AS A,
    NULL AS B,
    NULL AS S,
    NULL AS C
FROM sales AS s
LEFT JOIN items AS i
  ON i.id = s.item_id
 AND i.user_id = s.user_id
WHERE s.user_id = :user_id
  AND s.status IN ('paid','shipped','completed')
ORDER BY s.sold_at DESC NULLS LAST, s.id DESC
LIMIT :limit OFFSET :offset;
"""

SOLD_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE s.user_id = :user_id
  AND s.status IN ('paid','shipped','completed');
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
FULFILLMENT_IN_TRANSIT_SQL = """
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
  AND s.shipped_at IS NOT NULL
  AND s.delivered_at IS NULL
ORDER BY s.shipped_at DESC NULLS LAST, s.id DESC
LIMIT :limit OFFSET :offset;
"""

FULFILLMENT_IN_TRANSIT_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE s.user_id = :user_id
  AND s.shipped_at IS NOT NULL
  AND s.delivered_at IS NULL;
"""

# Delivered: Orders that have been delivered
FULFILLMENT_DELIVERED_SQL = """
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
  AND s.delivered_at IS NOT NULL
ORDER BY s.delivered_at DESC NULLS LAST, s.id DESC
LIMIT :limit OFFSET :offset;
"""

FULFILLMENT_DELIVERED_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE s.user_id = :user_id
  AND s.delivered_at IS NOT NULL;
"""

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
    where_clause = f"{where_clause} AND i.is_active IS TRUE"

    query_sql = ACTIVE_ITEMS_SQL.format(where_clause=where_clause)
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
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """
    Fetch sold items (sales records) for a user.
    NOTE: This returns SALES, not items from inventory.
    Filters are currently ignored but kept for API compatibility.
    """
    query_params = {"user_id": user_id, "limit": limit, "offset": offset}

    items = _rows_to_objects(session.execute(text(SOLD_ITEMS_SQL), query_params))
    total = session.execute(text(SOLD_COUNT_SQL), {"user_id": user_id}).scalar_one()
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


def fetch_fulfillment_in_transit(
    session: Session,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """Fetch orders that are shipped but not yet delivered (delivered_at IS NULL)"""
    query_params = {"user_id": user_id, "limit": limit, "offset": offset}
    items = _rows_to_objects(session.execute(text(FULFILLMENT_IN_TRANSIT_SQL), query_params))
    total = session.execute(text(FULFILLMENT_IN_TRANSIT_COUNT_SQL), {"user_id": user_id}).scalar_one()
    return items, total


def fetch_fulfillment_delivered(
    session: Session,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    """Fetch orders that have been delivered (delivered_at IS NOT NULL)"""
    query_params = {"user_id": user_id, "limit": limit, "offset": offset}
    items = _rows_to_objects(session.execute(text(FULFILLMENT_DELIVERED_SQL), query_params))
    total = session.execute(text(FULFILLMENT_DELIVERED_COUNT_SQL), {"user_id": user_id}).scalar_one()
    return items, total


def detect_thumbnail_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(THUMBNAIL_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)


def detect_sale_title_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(SALE_TITLE_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)
