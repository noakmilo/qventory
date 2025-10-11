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
    alias: str = "i",
) -> Tuple[str, Dict[str, object]]:
    clauses = [f"{alias}.user_id = :user_id"]
    params: Dict[str, object] = {"user_id": user_id}

    if search:
        clauses.append(f"({alias}.title ILIKE :search OR {alias}.sku ILIKE :search)")
        params["search"] = f"%{search}%"

    if A:
        clauses.append(f"{alias}.A = :A")
        params["A"] = A
    if B:
        clauses.append(f"{alias}.B = :B")
        params["B"] = B
    if S:
        clauses.append(f"{alias}.S = :S")
        params["S"] = S
    if C:
        clauses.append(f"{alias}.C = :C")
        params["C"] = C

    if platform:
        column = PLATFORM_COLUMNS.get(platform)
        if column:
            clauses.append(f"{alias}.{column} IS NOT NULL")

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
        i.last_ebay_sync,
        lm.latest_listed_at,
        lm.latest_synced_at,
        COALESCE(
            lm.latest_listed_at,
            i.listing_date::timestamp,
            i.last_ebay_sync,
            i.created_at
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
WITH filtered AS (
    SELECT
        s.user_id,
        s.item_id,
        i.id AS item_pk,
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
        s.sold_at,
        s.shipped_at,
        s.delivered_at,
        s.sold_price
    FROM sales AS s
    JOIN items AS i
      ON i.id = s.item_id
     AND i.user_id = s.user_id
    WHERE s.item_id IS NOT NULL
      AND s.status IN ('paid','shipped','completed')
      AND {item_filters}
      AND s.user_id = :user_id
),
sold AS (
    SELECT
        f.item_pk AS id,
        f.user_id,
        MAX(f.sold_at)      AS last_sold_at,
        MAX(f.shipped_at)   AS last_shipped_at,
        MAX(f.delivered_at) AS last_delivered_at,
        COUNT(*)            AS sale_count,
        SUM(f.sold_price)   AS total_revenue,
        MAX(f.title)        AS title,
        MAX(f.sku)          AS sku,
        MAX(f.item_thumb)   AS item_thumb,
        MAX(f.item_price)   AS item_price,
        MAX(f.item_cost)    AS item_cost,
        MAX(f.supplier)     AS supplier,
        MAX(f.location_code) AS location_code,
        MAX(f.web_url)      AS web_url,
        MAX(f.ebay_url)     AS ebay_url,
        MAX(f.amazon_url)   AS amazon_url,
        MAX(f.mercari_url)  AS mercari_url,
        MAX(f.vinted_url)   AS vinted_url,
        MAX(f.poshmark_url) AS poshmark_url,
        MAX(f.depop_url)    AS depop_url,
        MAX(f.ebay_listing_id) AS ebay_listing_id
    FROM filtered AS f
    GROUP BY f.item_pk, f.user_id
)
SELECT
    sold.*,
    ls.marketplace,
    ls.marketplace_url,
    ls.status AS listing_status,
    ls.ended_at
FROM sold
LEFT JOIN LATERAL (
    SELECT l.marketplace,
           l.marketplace_url,
           l.status,
           l.ended_at
    FROM listings AS l
    WHERE l.item_id = sold.id
      AND l.user_id = sold.user_id
    ORDER BY l.ended_at DESC NULLS LAST, l.listed_at DESC NULLS LAST
    LIMIT 1
) AS ls ON TRUE
ORDER BY sold.last_sold_at DESC NULLS LAST, sold.id DESC
LIMIT :limit OFFSET :offset;
"""

SOLD_COUNT_SQL = """
WITH filtered AS (
    SELECT
        s.item_id,
        i.id AS item_pk
    FROM sales AS s
    JOIN items AS i
      ON i.id = s.item_id
     AND i.user_id = s.user_id
    WHERE s.item_id IS NOT NULL
      AND s.status IN ('paid','shipped','completed')
      AND {item_filters}
      AND s.user_id = :user_id
)
SELECT COUNT(DISTINCT filtered.item_pk) FROM filtered;
"""

ENDED_ITEMS_SQL = """
WITH ended AS (
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
        COALESCE(
            MAX(CASE WHEN l.status IN ('ended','deleted') THEN l.ended_at END),
            i.updated_at,
            i.created_at
        ) AS ended_ts
    FROM items AS i
    LEFT JOIN listings AS l
      ON l.item_id = i.id
     AND l.user_id = i.user_id
    WHERE {where_clause}
    GROUP BY i.id, i.user_id, i.title, i.sku, i.item_thumb, i.item_price, i.item_cost,
             i.supplier, i.location_code, i.web_url, i.ebay_url, i.amazon_url, i.mercari_url,
             i.vinted_url, i.poshmark_url, i.depop_url, i.ebay_listing_id, i.updated_at, i.created_at
)
SELECT
    ended.*,
    ls.marketplace,
    ls.marketplace_url,
    ls.status AS listing_status
FROM ended
LEFT JOIN LATERAL (
    SELECT l.marketplace,
           l.marketplace_url,
           l.status,
           l.ended_at
    FROM listings AS l
    WHERE l.item_id = ended.id
      AND l.user_id = ended.user_id
    ORDER BY l.ended_at DESC NULLS LAST, l.updated_at DESC NULLS LAST
    LIMIT 1
) AS ls ON TRUE
ORDER BY ended.ended_ts DESC NULLS LAST, ended.id DESC
LIMIT :limit OFFSET :offset;
"""

ENDED_COUNT_SQL = """
SELECT COUNT(*)
FROM items AS i
WHERE {where_clause};
"""

FULFILLMENT_SQL = """
WITH fulfillment_events AS (
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
        CASE
            WHEN s.delivered_at IS NOT NULL THEN 'delivered'
            WHEN s.shipped_at IS NOT NULL THEN 'shipped'
            ELSE 'pending'
        END AS fulfillment_state,
        GREATEST(
            COALESCE(s.delivered_at, '-infinity'::timestamp),
            COALESCE(s.shipped_at, '-infinity'::timestamp)
        ) AS event_ts,
        COALESCE(s.item_title, i.title) AS resolved_title,
        COALESCE(s.item_sku, i.sku)     AS resolved_sku,
        i.item_thumb,
        i.location_code
    FROM sales AS s
    LEFT JOIN items AS i
      ON i.id = s.item_id
     AND i.user_id = s.user_id
    WHERE s.user_id = :user_id
      AND (s.shipped_at IS NOT NULL OR s.delivered_at IS NOT NULL)
)
SELECT
    fe.id,
    fe.user_id,
    fe.item_id,
    fe.marketplace,
    fe.marketplace_order_id,
    fe.item_title,
    fe.item_sku,
    fe.buyer_username,
    fe.ebay_buyer_username,
    fe.carrier,
    fe.tracking_number,
    fe.sold_price,
    fe.shipping_cost,
    fe.shipped_at,
    fe.delivered_at,
    fe.status,
    fe.fulfillment_state,
    fe.event_ts,
    fe.resolved_title,
    fe.resolved_sku,
    fe.item_thumb,
    fe.location_code
FROM fulfillment_events AS fe
ORDER BY fe.event_ts DESC NULLS LAST, fe.id DESC
LIMIT :limit OFFSET :offset;
"""

FULFILLMENT_COUNT_SQL = """
SELECT COUNT(*)
FROM sales AS s
WHERE s.user_id = :user_id
  AND (s.shipped_at IS NOT NULL OR s.delivered_at IS NOT NULL);
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
    item_filters, params = _build_item_filters(
        user_id,
        search=search,
        A=A,
        B=B,
        S=S,
        C=C,
        platform=platform,
    )

    query_sql = SOLD_ITEMS_SQL.format(item_filters=item_filters)
    count_sql = SOLD_COUNT_SQL.format(item_filters=item_filters)

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
    limit: int = 200,
    offset: int = 0,
) -> Tuple[List[SimpleNamespace], int]:
    query_params = {"user_id": user_id, "limit": limit, "offset": offset}
    items = _rows_to_objects(session.execute(text(FULFILLMENT_SQL), query_params))
    total = session.execute(text(FULFILLMENT_COUNT_SQL), {"user_id": user_id}).scalar_one()
    return items, total


def detect_thumbnail_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(THUMBNAIL_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)


def detect_sale_title_mismatches(session: Session, *, user_id: int) -> List[SimpleNamespace]:
    result = session.execute(text(SALE_TITLE_MISMATCH_SQL), {"user_id": user_id})
    return _rows_to_objects(result)
