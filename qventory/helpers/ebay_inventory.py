"""
eBay Inventory API Helper
Functions to fetch and sync inventory from eBay Sell API
"""
import os
import sys
import requests
from datetime import datetime
from collections import OrderedDict
import xml.etree.ElementTree as ET
from qventory.models.marketplace_credential import MarketplaceCredential

def log_inv(msg):
    """Helper function for logging"""
    print(f"[EBAY_INVENTORY] {msg}", file=sys.stderr, flush=True)

EBAY_ENV = os.environ.get('EBAY_ENV', 'production')

if EBAY_ENV == 'production':
    EBAY_API_BASE = "https://api.ebay.com"
else:
    EBAY_API_BASE = "https://api.sandbox.ebay.com"

if EBAY_ENV == 'production':
    TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
else:
    TRADING_API_URL = "https://api.sandbox.ebay.com/ws/api.dll"

TRADING_COMPAT_LEVEL = os.environ.get('EBAY_TRADING_COMPAT_LEVEL', '1145')
_LISTING_TIME_CACHE = OrderedDict()
_LISTING_TIME_CACHE_MAX = 512
_XML_NS = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
EBAY_STORE_SUBSCRIPTION_FEES = {
    "STARTER": 7.95,
    "BASIC": 27.95,
    "PREMIUM": 74.95,
    "ANCHOR": 349.95
}
EBAY_STORE_SUBSCRIPTION_LIMITS = {
    "STARTER": 250,
    "BASIC": 1000,
    "PREMIUM": 10000,
    "ANCHOR": 25000,
    "ENTERPRISE": 100000
}


def get_user_access_token(user_id):
    """
    Get valid access token for user's eBay account
    Auto-refreshes if expired

    Args:
        user_id: Qventory user ID

    Returns:
        str: Valid access token or None if not connected
    """
    from qventory.routes.ebay_auth import refresh_access_token, log
    from qventory.extensions import db
    from datetime import timedelta

    # Force refresh from database (avoid stale cache in multi-worker environment)
    db.session.expire_all()

    credential = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay',
        is_active=True
    ).first()

    if not credential:
        return None

    # Check if token is expired or about to expire (within 5 minutes)
    if credential.token_expires_at and credential.token_expires_at < datetime.utcnow() + timedelta(minutes=5):
        log(f"Access token expired for user {user_id}, refreshing...")

        try:
            # Refresh the token
            refresh_token = credential.get_refresh_token()
            if not refresh_token:
                log("No refresh token available")
                return None

            tokens = refresh_access_token(refresh_token)

            # Update credential
            credential.set_access_token(tokens['access_token'])
            if tokens.get('refresh_token'):
                credential.set_refresh_token(tokens['refresh_token'])
            credential.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens['expires_in'])
            credential.updated_at = datetime.utcnow()
            db.session.commit()

            log("Token refreshed successfully")
            return tokens['access_token']
        except Exception as e:
            log(f"Failed to refresh token: {str(e)}")
            return None

    return credential.get_access_token()


def normalize_store_subscription_level(level):
    if not level:
        return None
    return str(level).strip().upper()


def infer_store_subscription_level(monthly_fee):
    if monthly_fee is None:
        return None
    try:
        fee_value = float(monthly_fee)
    except (TypeError, ValueError):
        return None
    for level, fee in EBAY_STORE_SUBSCRIPTION_FEES.items():
        if abs(fee_value - fee) < 0.01:
            return level
    if fee_value >= 300:
        return "ANCHOR"
    if fee_value >= 70:
        return "PREMIUM"
    if fee_value >= 20:
        return "BASIC"
    if fee_value >= 1:
        return "STARTER"
    return None


def get_store_listing_limit(level, monthly_fee=0.0):
    normalized = normalize_store_subscription_level(level)
    if normalized and normalized in EBAY_STORE_SUBSCRIPTION_LIMITS:
        return EBAY_STORE_SUBSCRIPTION_LIMITS[normalized]
    inferred = infer_store_subscription_level(monthly_fee)
    if inferred and inferred in EBAY_STORE_SUBSCRIPTION_LIMITS:
        return EBAY_STORE_SUBSCRIPTION_LIMITS[inferred]
    return None


def get_ebay_store_subscription(user_id):
    """
    Fetch eBay Store subscription level and monthly fee from Trading API.
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {
            'success': False,
            'error': 'missing_access_token',
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    app_id = os.environ.get('EBAY_CLIENT_ID')
    if not app_id:
        return {
            'success': False,
            'error': 'missing_app_id',
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetStoreRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <DetailLevel>ReturnAll</DetailLevel>
</GetStoreRequest>'''

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'GetStore',
        'X-EBAY-API-APP-NAME': app_id,
        'X-EBAY-API-IAF-TOKEN': access_token,
        'Content-Type': 'text/xml'
    }

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
    except requests.RequestException as exc:
        log_inv(f"Trading API GetStore network error: {exc}")
        return {
            'success': False,
            'error': str(exc),
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    if response.status_code != 200:
        log_inv(f"Trading API GetStore error: {response.status_code} {response.text[:500]}")
        return {
            'success': False,
            'error': f'status_{response.status_code}',
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        log_inv(f"Trading API GetStore parse error: {exc}")
        return {
            'success': False,
            'error': 'parse_error',
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    ack = root.find('ebay:Ack', _XML_NS)
    if ack is not None and ack.text in ['Failure', 'PartialFailure']:
        error_msg = None
        error_elem = root.find('.//ebay:Errors/ebay:LongMessage', _XML_NS)
        if error_elem is not None:
            error_msg = error_elem.text
        log_inv(f"Trading API GetStore failure: {error_msg or 'unknown error'}")
        return {
            'success': False,
            'error': error_msg or 'api_failure',
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    store_elem = root.find('.//ebay:Store', _XML_NS)
    if store_elem is None:
        return {
            'success': True,
            'error': None,
            'has_store': False,
            'subscription_level': None,
            'monthly_fee': 0.0
        }

    level_elem = store_elem.find('ebay:SubscriptionLevel', _XML_NS)
    level = level_elem.text.strip() if level_elem is not None and level_elem.text else None
    level_key = level.upper() if level else None
    monthly_fee = EBAY_STORE_SUBSCRIPTION_FEES.get(level_key, 0.0)

    return {
        'success': True,
        'error': None,
        'has_store': True,
        'subscription_level': level,
        'monthly_fee': monthly_fee
    }


def sync_ebay_store_subscription(user_id):
    """
    Persist store subscription fee on the marketplace credential.
    """
    from qventory.extensions import db

    result = get_ebay_store_subscription(user_id)
    if not result.get('success'):
        return result

    subscription_level = normalize_store_subscription_level(result.get('subscription_level'))
    credential = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay'
    ).first()

    if not credential:
        result['success'] = False
        result['error'] = 'missing_credential'
        return result

    credential.ebay_store_subscription = result.get('monthly_fee', 0.0)
    credential.ebay_store_subscription_level = subscription_level
    credential.updated_at = datetime.utcnow()
    db.session.commit()

    return result


def _parse_ebay_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    log_inv(f"⚠️  Unable to parse eBay datetime: {value}")
    return None


def _set_listing_time_cache(key, value):
    _LISTING_TIME_CACHE[key] = value
    while len(_LISTING_TIME_CACHE) > _LISTING_TIME_CACHE_MAX:
        _LISTING_TIME_CACHE.popitem(last=False)


def get_listing_time_details(user_id, listing_id):
    """
    Fetch listing start/end time from Trading API GetItem call.
    Results are cached per user/listing to reduce API calls.
    """
    if not listing_id:
        return {}

    cache_key = (user_id, listing_id)
    if cache_key in _LISTING_TIME_CACHE:
        return _LISTING_TIME_CACHE[cache_key]

    access_token = get_user_access_token(user_id)
    if not access_token:
        log_inv("Cannot fetch listing times: no access token")
        return {}

    app_id = os.environ.get('EBAY_CLIENT_ID')
    if not app_id:
        log_inv("Cannot fetch listing times: missing EBAY_CLIENT_ID")
        return {}

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'GetItem',
        'X-EBAY-API-APP-NAME': app_id,
        'X-EBAY-API-IAF-TOKEN': access_token,
        'Content-Type': 'text/xml'
    }

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ItemID>{listing_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>'''

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
        log_inv(f"GetItem status for {listing_id}: {response.status_code}")
        if response.status_code != 200:
            log_inv(f"GetItem error body: {response.text[:500]}")
            return {}

        root = ET.fromstring(response.content)
        ack = root.find('ebay:Ack', _XML_NS)
        if ack is not None and ack.text in ['Failure', 'PartialFailure']:
            error = root.find('.//ebay:Errors/ebay:LongMessage', _XML_NS)
            if error is not None:
                log_inv(f"GetItem error: {error.text}")
            return {}

        item_elem = root.find('ebay:Item', _XML_NS)
        if item_elem is None:
            log_inv("GetItem response missing Item element")
            return {}

        start_elem = item_elem.find('ebay:ListingDetails/ebay:StartTime', _XML_NS)
        if start_elem is None:
            start_elem = item_elem.find('ebay:StartTime', _XML_NS)
        end_elem = item_elem.find('ebay:ListingDetails/ebay:EndTime', _XML_NS)
        if end_elem is None:
            end_elem = item_elem.find('ebay:EndTime', _XML_NS)

        start_time = _parse_ebay_datetime(start_elem.text if start_elem is not None else None)
        end_time = _parse_ebay_datetime(end_elem.text if end_elem is not None else None)

        payload = {
            'start_time': start_time,
            'end_time': end_time
        }
        _set_listing_time_cache(cache_key, payload)
        return payload
    except Exception as exc:
        log_inv(f"Exception calling GetItem for {listing_id}: {exc}")
        return {}


def get_inventory_items(user_id, limit=200, offset=0):
    """
    Get inventory items from eBay Inventory API

    Args:
        user_id: Qventory user ID
        limit: Max items per page (max 200)
        offset: Pagination offset

    Returns:
        dict with 'items' list and 'total' count
    """
    log_inv(f"Getting inventory items for user {user_id} (limit={limit}, offset={offset})")

    try:
        access_token = get_user_access_token(user_id)
        if not access_token:
            log_inv("ERROR: No valid eBay access token available")
            raise Exception("No valid eBay access token available")
    except Exception as e:
        if 'InvalidToken' in str(type(e)) or 'InvalidSignature' in str(e):
            log_inv("ERROR: Token decryption failed - SECRET_KEY may have changed")
            raise Exception("eBay credentials are corrupted. Please disconnect and reconnect your eBay account in Settings.")
        raise

    url = f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item"
    log_inv(f"API URL: {url}")
    log_inv(f"Access token (first 20 chars): {access_token[:20]}...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    params = {
        'limit': min(limit, 200),  # Max 200 per eBay API
        'offset': offset
    }

    log_inv(f"Making request to eBay Inventory API...")
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        log_inv(f"Response status: {response.status_code}")

        if response.status_code != 200:
            log_inv(f"ERROR response body: {response.text[:500]}")

        response.raise_for_status()

        data = response.json()
        item_count = len(data.get('inventoryItems', []))
        total = data.get('total', 0)

        log_inv(f"Got {item_count} items (total available: {total})")

        return {
            'items': data.get('inventoryItems', []),
            'total': total,
            'limit': limit,
            'offset': offset
        }
    except Exception as e:
        log_inv(f"ERROR calling eBay API: {str(e)}")
        raise


def get_active_listings(user_id, limit=200, offset=0):
    """
    Get active listings (offers) from eBay

    Args:
        user_id: Qventory user ID
        limit: Max items per page
        offset: Pagination offset

    Returns:
        dict with 'offers' list and 'total' count
    """
    log_inv(f"Getting active listings (offers) for user {user_id} (limit={limit}, offset={offset})")

    access_token = get_user_access_token(user_id)
    if not access_token:
        raise Exception("No valid eBay access token available")

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer"
    log_inv(f"Offers API URL: {url}")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    marketplace_id = os.environ.get('EBAY_MARKETPLACE_ID', 'EBAY_US')

    params = {
        'limit': min(limit, 200),
        'offset': offset
        # Note: marketplace_id filter removed - was causing 400 errors
        # eBay will return all offers for the authenticated user
    }

    log_inv(f"Making request to eBay Offers API...")
    response = requests.get(url, headers=headers, params=params, timeout=30)
    log_inv(f"Offers API response status: {response.status_code}")

    if response.status_code != 200:
        log_inv(f"ERROR response body: {response.text[:500]}")

    response.raise_for_status()

    data = response.json()
    log_inv(f"Offers API response data keys: {list(data.keys())}")
    log_inv(f"Number of offers: {len(data.get('offers', []))}")
    log_inv(f"Total available: {data.get('total', 0)}")

    # Log first offer details for debugging
    if data.get('offers'):
        first_offer = data['offers'][0]
        log_inv(f"First offer sample: {list(first_offer.keys())}")

    return {
        'offers': data.get('offers', []),
        'total': data.get('total', 0),
        'limit': limit,
        'offset': offset
    }


def _normalize_listing_key(item):
    """Generate a deduplication key for an eBay item payload."""
    listing_id = item.get('ebay_listing_id') or item.get('listing_id')
    if listing_id:
        return f"id:{str(listing_id).strip()}"

    product = item.get('product')
    if isinstance(product, dict):
        title = product.get('title') or ''
    else:
        title = item.get('title', '')
    normalized_title = ' '.join(title.split()).lower()
    sku = (item.get('sku') or item.get('ebay_sku') or '').strip().lower()
    price = item.get('item_price')
    source = item.get('source', 'unknown')
    return f"title:{normalized_title}|sku:{sku}|price:{price}|source:{source}"


def deduplicate_ebay_items(items):
    """
    Remove duplicate listings returned by eBay APIs.

    Duplicates primarily use ebay_listing_id/listing_id, but we fall back to
    title+SKU+price+source when IDs are missing. When duplicates are found,
    we merge missing fields (e.g., SKU from Trading API) into the first item.
    """
    seen = {}
    order = []
    duplicates = []
    deduped = []

    def merge_missing(target, incoming):
        if not isinstance(target, dict) or not isinstance(incoming, dict):
            return
        for field in [
            'sku', 'ebay_sku', 'ebay_listing_id', 'listing_id',
            'ebay_url', 'item_price', 'listing_status',
            'listing_start_time', 'listing_end_time'
        ]:
            if not target.get(field) and incoming.get(field):
                target[field] = incoming.get(field)

        target_product = target.get('product')
        incoming_product = incoming.get('product')
        if isinstance(target_product, dict) and isinstance(incoming_product, dict):
            for field in ['title', 'description']:
                if not target_product.get(field) and incoming_product.get(field):
                    target_product[field] = incoming_product.get(field)
            if (not target_product.get('imageUrls')) and incoming_product.get('imageUrls'):
                target_product['imageUrls'] = incoming_product.get('imageUrls')
        elif not target.get('product') and isinstance(incoming_product, dict):
            target['product'] = incoming_product

    for item in items:
        try:
            key = _normalize_listing_key(item or {})
        except Exception as exc:
            log_inv(f"⚠️  Could not generate dedup key, keeping item. Error: {exc}")
            key = None

        if key and key in seen:
            duplicates.append(item)
            merge_missing(seen[key], item)
            continue

        if key:
            seen[key] = item
            order.append(key)
        else:
            deduped.append(item)

    for key in order:
        item = seen.get(key)
        if item:
            deduped.append(item)

    if duplicates:
        log_inv(f"⚠️  Removed {len(duplicates)} duplicate listings from eBay payload")
        sample = duplicates[:5]
        for dup in sample:
            listing_id = dup.get('ebay_listing_id') or dup.get('listing_id') or 'N/A'
            product = dup.get('product') if isinstance(dup.get('product'), dict) else {}
            title = product.get('title') or dup.get('title') or ''
            source = dup.get('source', 'unknown')
            log_inv(f"     Duplicate listing {listing_id}: {title[:70]} (source={source})")
        if len(duplicates) > len(sample):
            log_inv(f"     ...and {len(duplicates) - len(sample)} more duplicates trimmed")

    return deduped, duplicates


def get_all_inventory(user_id, max_items=1000):
    """
    Get all inventory items (paginated)

    Falls back to Offers API if Inventory API returns 0 items
    (Inventory API only shows new-style inventory, Offers API shows all active listings)

    Args:
        user_id: Qventory user ID
        max_items: Maximum total items to fetch

    Returns:
        list of combined inventory items with offer data
    """
    log_inv(f"Starting inventory fetch for user {user_id}")
    all_items = []
    offset = 0
    limit = 200

    # Try Inventory API first
    while len(all_items) < max_items:
        result = get_inventory_items(user_id, limit=limit, offset=offset)
        items = result['items']

        if not items:
            break

        all_items.extend(items)

        # Keep paginating until a page returns fewer than the requested limit
        # (eBay's reported "total" can be inaccurate/mismatched).
        if len(items) < limit:
            break

        offset += limit

    # If Inventory API is partial or empty, enrich with Offers/Trading to avoid missing legacy listings
    try_offers = len(all_items) < max_items

    if try_offers:
        try:
            offset = 0
            while len(all_items) < max_items:
                result = get_active_listings(user_id, limit=limit, offset=offset)
                offers = result['offers']

                log_inv(f"Offers API returned {len(offers)} offers (total: {result.get('total', 'unknown')})")

                if not offers:
                    break

                # Convert offers to inventory-like format
                for offer in offers:
                    sku = offer.get('sku', '')
                    listing_id = offer.get('listingId')
                    pricing = offer.get('pricingSummary', {})
                    price_value = pricing.get('price', {}).get('value', 0)
                    available_quantity = offer.get('availableQuantity', 0)
                    listing = offer.get('listing', {})

                    item_data = {
                        'sku': sku,
                        'product': {
                            'title': listing.get('title', offer.get('merchantLocationKey', f'Listing {listing_id}')),
                            'description': listing.get('description', ''),
                            'imageUrls': listing.get('pictureUrls', [])
                        },
                        'availability': {
                            'shipToLocationAvailability': {
                                'quantity': available_quantity
                            }
                        },
                        'condition': offer.get('listingPolicies', {}).get('condition', 'USED_EXCELLENT'),
                        'ebay_listing_id': listing_id,
                        'ebay_offer_id': offer.get('offerId'),
                        'item_price': float(price_value) if price_value else 0,
                        'ebay_url': f"https://www.ebay.com/itm/{listing_id}" if listing_id else None,
                        'listing_status': offer.get('status', 'UNKNOWN'),
                        'source': 'offers_api'
                    }

                    all_items.append(item_data)

                # Keep paginating while we receive full pages; "total" can be unreliable.
                if len(offers) < limit:
                    break

                offset += limit

            log_inv(f"Offers API augmentation complete: total aggregated items={len(all_items)}")

        except Exception as e:
            log_inv(f"ERROR in Offers API augmentation: {str(e)}")

    # Final fallback: Trading API if we still have room
    if len(all_items) < max_items:
        try:
            trading_items = get_active_listings_trading_api(user_id, max_items=max_items, collect_failures=False)
            if trading_items:
                log_inv(f"Trading API returned {len(trading_items)} active listings")
                all_items.extend(trading_items)
        except Exception as trading_error:
            log_inv(f"ERROR in Trading API fallback: {str(trading_error)}")

    deduped_items, _ = deduplicate_ebay_items(all_items)
    return deduped_items[:max_items]


def get_ebay_orders(user_id, days_back=None, max_orders=5000, start_date=None, end_date=None):
    """
    Get completed orders from eBay Fulfillment API with pagination

    Args:
        user_id: Qventory user ID
        days_back: How many days back to fetch orders (ignored if start_date provided)
        max_orders: Maximum orders to fetch (default 5000)
        start_date: Optional datetime to bound range (inclusive)
        end_date: Optional datetime to bound range (inclusive, defaults to now)

    Returns:
        list of order dicts with sale information
    """
    from datetime import datetime, timedelta

    if end_date is None:
        end_date = datetime.utcnow()

    if start_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    if start_date:
        date_from = start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        date_to = end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        log_inv(f"Getting eBay orders for user {user_id} between {date_from} and {date_to}")
        filter_param = f'creationdate:[{date_from}..{date_to}]'
    elif days_back:
        log_inv(f"Getting eBay orders for user {user_id} (last {days_back} days)")
        start_dt = end_date - timedelta(days=days_back)
        date_from = start_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        date_to = end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        filter_param = f'creationdate:[{date_from}..{date_to}]'
    else:
        log_inv(f"Getting ALL eBay orders for user {user_id} (lifetime)")
        filter_param = None

    access_token = get_user_access_token(user_id)
    if not access_token:
        raise Exception("No valid eBay access token available")

    url = f"{EBAY_API_BASE}/sell/fulfillment/v1/order"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    all_orders = []
    offset = 0
    limit = 200  # eBay API max per request

    # Paginate through all orders
    while len(all_orders) < max_orders:
        params = {
            'limit': limit,
            'offset': offset
        }

        if filter_param:
            params['filter'] = filter_param

        try:
            log_inv(f"Fetching page: offset={offset}, limit={limit}")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code != 200:
                log_inv(f"ERROR response: {response.text[:500]}")
                response.raise_for_status()

            data = response.json()
            orders = data.get('orders', [])
            total = data.get('total', 0)

            log_inv(f"Page result: {len(orders)} orders (total available: {total})")

            if not orders:
                log_inv("No more orders, stopping pagination")
                break

            all_orders.extend(orders)
            log_inv(f"Total fetched so far: {len(all_orders)}")

            # Check if we've fetched all available orders
            if len(all_orders) >= total:
                log_inv(f"Fetched all {total} available orders")
                break

            # Move to next page
            offset += limit

        except Exception as e:
            log_inv(f"ERROR fetching eBay orders: {str(e)}")
            raise

    log_inv(f"✅ Total orders fetched: {len(all_orders)}")
    return all_orders[:max_orders]


def get_active_listings_trading_api(user_id, max_items=1000, collect_failures=True):
    """
    Get active listings using Trading API (legacy but reliable)
    Uses GetMyeBaySelling call which works with all listing types

    Args:
        user_id: Qventory user ID
        max_items: Maximum items to fetch (supports pagination for 200+)
        collect_failures: If True, return tuple (items, failed_items). If False, return only items list.

    Returns:
        If collect_failures=True: tuple (list of items, list of failed items dicts)
        If collect_failures=False: list of items in normalized format
    """
    log_inv(f"Attempting Trading API GetMyeBaySelling for user {user_id}")

    access_token = get_user_access_token(user_id)
    if not access_token:
        log_inv("No access token available")
        return ([], []) if collect_failures else []

    app_id = os.environ.get('EBAY_CLIENT_ID')

    ns = _XML_NS

    all_items = []
    failed_items = []  # Track items that failed to parse
    page_number = 1
    entries_per_page = 200  # Max allowed by eBay
    total_pages = 1  # Will be updated from first response

    # Paginate through all results
    while page_number <= total_pages and len(all_items) < max_items:
        log_inv(f"Fetching page {page_number}/{total_pages} (entries per page: {entries_per_page})")

        # Build XML request for GetMyeBaySelling
        xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>{entries_per_page}</EntriesPerPage>
      <PageNumber>{page_number}</PageNumber>
    </Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>'''

        headers = {
            'X-EBAY-API-SITEID': '0',  # 0 = US
            'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
            'X-EBAY-API-CALL-NAME': 'GetMyeBaySelling',
            'X-EBAY-API-APP-NAME': app_id,
            'X-EBAY-API-IAF-TOKEN': access_token,
            'Content-Type': 'text/xml'
        }

        log_inv(f"Calling Trading API: {TRADING_API_URL}")
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
        log_inv(f"Trading API response status: {response.status_code}")

        if response.status_code != 200:
            log_inv(f"Trading API error: {response.text[:500]}")
            break

        # Parse XML response
        try:
            root = ET.fromstring(response.content)

            # Check for errors
            ack = root.find('ebay:Ack', ns)
            if ack is not None and ack.text in ['Failure', 'PartialFailure']:
                errors = root.findall('.//ebay:Errors', ns)
                for error in errors:
                    error_msg = error.find('ebay:LongMessage', ns)
                    if error_msg is not None:
                        log_inv(f"Trading API error: {error_msg.text}")
                break

            # Get pagination info from response
            pagination_result = root.find('.//ebay:ActiveList/ebay:PaginationResult', ns)
            if pagination_result is not None:
                total_pages_elem = pagination_result.find('ebay:TotalNumberOfPages', ns)
                total_entries_elem = pagination_result.find('ebay:TotalNumberOfEntries', ns)

                if total_pages_elem is not None:
                    total_pages = int(total_pages_elem.text)
                if total_entries_elem is not None:
                    total_entries = int(total_entries_elem.text)
                    log_inv(f"Total listings available: {total_entries} across {total_pages} page(s)")

            # Extract active listings
            item_array = root.find('.//ebay:ActiveList/ebay:ItemArray', ns)

            if item_array is None:
                log_inv("No ItemArray found in response")
                break

            items_in_page = 0
            for item_elem in item_array.findall('ebay:Item', ns):
                try:
                    # Extract item data
                    item_id = item_elem.find('ebay:ItemID', ns)
                    title = item_elem.find('ebay:Title', ns)

                    # Price - with robust parsing
                    price = 0
                    try:
                        selling_status = item_elem.find('ebay:SellingStatus', ns)
                        current_price = selling_status.find('ebay:CurrentPrice', ns) if selling_status is not None else None
                        if current_price is not None and current_price.text:
                            price = float(current_price.text.strip())
                    except (ValueError, AttributeError) as e:
                        log_inv(f"Warning: Could not parse price for item, defaulting to 0: {str(e)}")
                        price = 0

                    # Quantity - with robust parsing
                    quantity = 1
                    try:
                        quantity_elem = item_elem.find('ebay:Quantity', ns)
                        if quantity_elem is not None and quantity_elem.text:
                            quantity = int(quantity_elem.text.strip())
                    except (ValueError, AttributeError) as e:
                        log_inv(f"Warning: Could not parse quantity for item, defaulting to 1: {str(e)}")
                        quantity = 1

                    # SKU (Custom Label). For variations, use first variation SKU.
                    sku_elem = item_elem.find('ebay:SKU', ns)
                    sku = sku_elem.text if sku_elem is not None else ''
                    variation_skus = []
                    if not sku:
                        var_sku_elems = item_elem.findall('.//ebay:Variations/ebay:Variation/ebay:SKU', ns)
                        for var_sku_elem in var_sku_elems:
                            if var_sku_elem is not None and var_sku_elem.text:
                                variation_skus.append(var_sku_elem.text.strip())
                        if variation_skus:
                            sku = variation_skus[0]

                    # Image
                    picture_details = item_elem.find('ebay:PictureDetails', ns)
                    image_url = None
                    if picture_details is not None:
                        gallery_url = picture_details.find('ebay:GalleryURL', ns)
                        if gallery_url is not None:
                            image_url = gallery_url.text

                    start_elem = item_elem.find('ebay:ListingDetails/ebay:StartTime', ns)
                    if start_elem is None:
                        start_elem = item_elem.find('ebay:StartTime', ns)
                    end_elem = item_elem.find('ebay:ListingDetails/ebay:EndTime', ns)
                    if end_elem is None:
                        end_elem = item_elem.find('ebay:EndTime', ns)
                    start_time = _parse_ebay_datetime(start_elem.text if start_elem is not None else None)
                    end_time = _parse_ebay_datetime(end_elem.text if end_elem is not None else None)

                    # Build normalized item
                    normalized = {
                        'sku': sku,
                        'product': {
                            'title': title.text if title is not None else 'Unknown',
                            'description': '',
                            'imageUrls': [image_url] if image_url else []
                        },
                        'availability': {
                            'shipToLocationAvailability': {
                                'quantity': quantity
                            }
                        },
                        'condition': 'USED_EXCELLENT',
                        'ebay_listing_id': item_id.text if item_id is not None else '',
                        'item_price': price,
                        'ebay_url': f"https://www.ebay.com/itm/{item_id.text}" if item_id is not None else None,
                        'listing_start_time': start_time,
                        'listing_end_time': end_time,
                        'source': 'trading_api',
                        'variation_skus': variation_skus
                    }
                    all_items.append(normalized)
                    items_in_page += 1

                except Exception as e:
                    # Collect failed item details
                    try:
                        failed_id_elem = item_elem.find('ebay:ItemID', ns)
                        failed_title_elem = item_elem.find('ebay:Title', ns)
                        failed_sku_elem = item_elem.find('ebay:SKU', ns)

                        failed_id = failed_id_elem.text if failed_id_elem is not None else None
                        failed_title = failed_title_elem.text if failed_title_elem is not None else None
                        failed_sku = failed_sku_elem.text if failed_sku_elem is not None else None

                        log_inv(f"❌ Error parsing item ID={failed_id or 'Unknown'}, Title={failed_title[:50] if failed_title else 'Unknown'}: {str(e)}")

                        # Collect failed item data
                        if collect_failures:
                            import traceback
                            failed_items.append({
                                'ebay_listing_id': failed_id,
                                'ebay_title': failed_title,
                                'ebay_sku': failed_sku,
                                'error_type': 'parsing_error',
                                'error_message': str(e),
                                'raw_data': ET.tostring(item_elem, encoding='unicode')[:5000],  # Store raw XML (limit to 5KB)
                                'traceback': traceback.format_exc()[:2000]
                            })
                    except Exception as inner_e:
                        log_inv(f"❌ Error parsing item (couldn't extract ID/title): {str(e)}")
                        log_inv(f"❌ Additional error during failure collection: {str(inner_e)}")
                        if collect_failures:
                            failed_items.append({
                                'ebay_listing_id': None,
                                'ebay_title': None,
                                'ebay_sku': None,
                                'error_type': 'critical_parsing_error',
                                'error_message': f"Primary: {str(e)}, Secondary: {str(inner_e)}",
                                'raw_data': None,
                                'traceback': None
                            })
                    continue

            log_inv(f"✓ Parsed {items_in_page} items from page {page_number}")

        except ET.ParseError as e:
            log_inv(f"XML parsing error: {str(e)}")
            log_inv(f"Response content: {response.text[:500]}")
            break
        except Exception as e:
            log_inv(f"Error processing Trading API response: {str(e)}")
            break

        # Move to next page
        page_number += 1

    # Final summary
    log_inv(f"=" * 60)
    log_inv(f"Trading API Summary:")
    log_inv(f"  eBay reported: {total_entries if 'total_entries' in locals() else 'Unknown'} total active listings")
    log_inv(f"  Successfully fetched: {len(all_items)} items")
    log_inv(f"  Failed to parse: {len(failed_items)} items")

    if 'total_entries' in locals():
        expected_total = total_entries
        actual_total = len(all_items) + len(failed_items)

        if actual_total < expected_total:
            still_missing = expected_total - actual_total
            log_inv(f"  ⚠️  STILL MISSING {still_missing} items ({still_missing/expected_total*100:.1f}%)")
            log_inv(f"  Possible causes:")
            log_inv(f"    - eBay API returned incomplete data")
            log_inv(f"    - Items don't meet API filter criteria")

        if len(failed_items) > 0:
            log_inv(f"  ⚠️  {len(failed_items)} items failed to parse and will be stored for retry")
    log_inv(f"=" * 60)

    # Deduplicate before returning
    deduped_items, duplicates = deduplicate_ebay_items(all_items)
    if duplicates:
        log_inv(f"Trading API deduplication complete: {len(deduped_items)} unique items returned")
    else:
        log_inv("Trading API returned unique listings (no duplicates detected)")
    all_items = deduped_items

    if collect_failures:
        return all_items[:max_items], failed_items
    else:
        return all_items[:max_items]


def get_listings_from_fulfillment_api(user_id, max_items=1000):
    """
    Extract active listings from recent orders using Fulfillment API
    This is a workaround when other APIs fail

    Args:
        user_id: Qventory user ID
        max_items: Maximum items to fetch

    Returns:
        list of items in normalized format
    """
    log_inv(f"Attempting Fulfillment API for user {user_id}")

    access_token = get_user_access_token(user_id)
    if not access_token:
        log_inv("No access token available")
        return []

    # Get recent orders (last 90 days)
    from datetime import datetime, timedelta
    created_after = (datetime.utcnow() - timedelta(days=90)).isoformat() + 'Z'

    url = f"{EBAY_API_BASE}/sell/fulfillment/v1/order"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    params = {
        'filter': f'creationdate:[{created_after}..]',
        'limit': 50
    }

    log_inv("Fetching recent orders from Fulfillment API...")
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code != 200:
        log_inv(f"Fulfillment API error: {response.status_code} - {response.text[:200]}")
        return []

    data = response.json()
    orders = data.get('orders', [])
    log_inv(f"Found {len(orders)} recent orders")

    # Extract unique listings from orders
    seen_listing_ids = set()
    items = []

    for order in orders:
        line_items = order.get('lineItems', [])
        for line_item in line_items:
            listing_id = line_item.get('legacyItemId')
            if not listing_id or listing_id in seen_listing_ids:
                continue

            seen_listing_ids.add(listing_id)

            title = line_item.get('title', '')
            sku = line_item.get('sku', '')
            image_url = line_item.get('image', {}).get('imageUrl')
            price = float(line_item.get('lineItemCost', {}).get('value', 0))

            normalized = {
                'sku': sku,
                'product': {
                    'title': title,
                    'description': '',
                    'imageUrls': [image_url] if image_url else []
                },
                'availability': {
                    'shipToLocationAvailability': {
                        'quantity': 1
                    }
                },
                'condition': 'USED_EXCELLENT',
                'ebay_listing_id': listing_id,
                'item_price': price,
                'ebay_url': f"https://www.ebay.com/itm/{listing_id}",
                'source': 'fulfillment_api'
            }
            items.append(normalized)

            if len(items) >= max_items:
                break

        if len(items) >= max_items:
            break

    log_inv(f"Extracted {len(items)} unique listings from orders")
    return items


def get_seller_listings_browse_api(user_id, max_items=1000):
    """
    Get seller's active listings using Browse API
    This is a fallback when Inventory and Offers APIs fail

    Args:
        user_id: Qventory user ID
        max_items: Maximum items to fetch

    Returns:
        list of items in normalized format
    """
    from qventory.models.marketplace_credential import MarketplaceCredential

    log_inv(f"Attempting Browse API for user {user_id}")

    # Get seller's eBay username from credentials
    credential = MarketplaceCredential.query.filter_by(
        user_id=user_id,
        marketplace='ebay',
        is_active=True
    ).first()

    if not credential or not credential.ebay_user_id:
        log_inv("No eBay username found in credentials")
        return []

    seller_username = credential.ebay_user_id
    log_inv(f"Seller username: {seller_username}")

    # If username is generic, we can't use Browse API
    if seller_username in ['eBay User', 'eBay Seller', None, '']:
        log_inv(f"Username '{seller_username}' is too generic for Browse API search")
        return []

    # Get application token (not user token) for Browse API
    client_id = os.environ.get('EBAY_CLIENT_ID')
    client_secret = os.environ.get('EBAY_CLIENT_SECRET')

    if not client_id or not client_secret:
        log_inv("Missing eBay app credentials")
        return []

    # Get application access token
    import base64
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    token_url = f"{EBAY_API_BASE}/identity/v1/oauth2/token"
    token_headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {auth_header}'
    }
    token_data = {
        'grant_type': 'client_credentials',
        'scope': 'https://api.ebay.com/oauth/api_scope'
    }

    log_inv("Getting application token for Browse API...")
    token_response = requests.post(token_url, headers=token_headers, data=token_data, timeout=30)

    if token_response.status_code != 200:
        log_inv(f"Failed to get app token: {token_response.status_code}")
        return []

    app_token = token_response.json().get('access_token')

    # Search for seller's items using Browse API
    browse_url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
    browse_headers = {
        'Authorization': f'Bearer {app_token}',
        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'
    }

    all_items = []
    offset = 0
    limit = 200

    while len(all_items) < max_items:
        params = {
            'q': f'*',
            'filter': f'sellers:{{{seller_username}}}',
            'limit': limit,
            'offset': offset
        }

        log_inv(f"Browse API search: offset={offset}, limit={limit}")
        browse_response = requests.get(browse_url, headers=browse_headers, params=params, timeout=30)

        if browse_response.status_code != 200:
            log_inv(f"Browse API error: {browse_response.status_code} - {browse_response.text[:200]}")
            break

        data = browse_response.json()
        items = data.get('itemSummaries', [])
        total = data.get('total', 0)

        log_inv(f"Browse API returned {len(items)} items (total: {total})")

        if not items:
            break

        # Convert Browse API items to normalized format
        for item in items:
            item_id = item.get('itemId')
            title = item.get('title', '')
            price_obj = item.get('price', {})
            price = float(price_obj.get('value', 0))
            image_url = item.get('image', {}).get('imageUrl')
            item_url = item.get('itemWebUrl')

            # Verify item_id matches URL to prevent title mismatch
            # Some Browse API responses can have stale data
            if item_url and item_id:
                # Extract ID from URL (e.g., https://www.ebay.com/itm/376512069186)
                url_id = item_url.split('/')[-1].split('?')[0]
                if url_id != item_id:
                    log_inv(f"WARNING: itemId mismatch - API says {item_id}, URL says {url_id}. Using URL ID.")
                    item_id = url_id

            # Build canonical eBay URL from item_id to ensure consistency
            canonical_url = f"https://www.ebay.com/itm/{item_id}" if item_id else item_url

            normalized = {
                'sku': '',  # Browse API doesn't return SKU
                'product': {
                    'title': title,
                    'description': '',
                    'imageUrls': [image_url] if image_url else []
                },
                'availability': {
                    'shipToLocationAvailability': {
                        'quantity': 1  # Browse API doesn't return exact quantity
                    }
                },
                'condition': item.get('condition', 'USED_EXCELLENT'),
                'ebay_listing_id': item_id,
                'item_price': price,
                'ebay_url': canonical_url,
                'source': 'browse_api'
            }
            all_items.append(normalized)

        if len(all_items) >= total:
            break

        offset += limit

    return all_items[:max_items]


def parse_ebay_inventory_item(ebay_item, process_images=True):
    """
    Parse eBay inventory item to Qventory format

    Handles both Inventory API and Offers API formats

    Args:
        ebay_item: eBay inventory item dict from API
        process_images: If True, download and upload images to Cloudinary (default True)

    Returns:
        dict with Qventory item fields
    """
    from qventory.helpers import is_valid_location_code, parse_location_code

    # Check source of data
    source = ebay_item.get('source', '')
    is_normalized = source in ['offers_api', 'browse_api', 'fulfillment_api', 'trading_api']

    if is_normalized:
        # Already normalized in get_all_inventory()
        product = ebay_item.get('product', {})
        title = product.get('title', '')
        description = product.get('description', '')
        images = product.get('imageUrls', [])

        # Get listing ID FIRST (needed for image upload)
        ebay_listing_id = ebay_item.get('ebay_listing_id')
        ebay_url = ebay_item.get('ebay_url')
        item_price = ebay_item.get('item_price', 0)

        # Process image: download from eBay, compress, upload to Cloudinary
        # Use ebay_listing_id as public_id to prevent image mix-ups
        item_thumb = None
        if images and process_images:
            from qventory.helpers.image_processor import download_and_upload_image
            ebay_image_url = images[0]
            log_inv(f"Processing image for: {title[:50]}")
            item_thumb = download_and_upload_image(
                ebay_image_url,
                target_size_kb=2,
                max_dimension=400,
                public_id=ebay_listing_id  # Use listing ID as unique identifier
            )
            if not item_thumb:
                log_inv(f"Failed to process image, using original URL")
                item_thumb = ebay_image_url  # Fallback to original URL
        elif images:
            item_thumb = images[0]  # Use original URL if not processing
        sku = ebay_item.get('sku', '')
        availability = ebay_item.get('availability', {})
        quantity = availability.get('shipToLocationAvailability', {}).get('quantity', 0)
        condition = ebay_item.get('condition', 'USED_EXCELLENT')

        # Always store eBay Custom SKU as location_code (location only; not a matching key)
        location_components = {}
        location_code = sku or None
        if sku and is_valid_location_code(sku):
            log_inv(f"Detected valid location code in eBay SKU: {sku}")
            location_components = parse_location_code(sku)
        elif sku:
            log_inv(f"eBay SKU '{sku}' is not a valid location code format (stored as location_code)")

        return {
            'title': title,
            'description': description,
            'item_thumb': item_thumb,
            'ebay_sku': sku,
            'quantity': quantity,
        'condition': condition,
        'ebay_listing_id': ebay_listing_id,
        'ebay_url': ebay_url,
        'item_price': item_price,
        'listing_start_time': ebay_item.get('listing_start_time'),
        'listing_end_time': ebay_item.get('listing_end_time'),
            'location_code': location_code,  # Parsed location code if valid
            'location_A': location_components.get('A'),
            'location_B': location_components.get('B'),
            'location_S': location_components.get('S'),
            'location_C': location_components.get('C'),
            'variation_skus': ebay_item.get('variation_skus', []),
            'ebay_item_data': ebay_item
        }
    else:
        # Original Inventory API format
        product = ebay_item.get('product', {})
        title = product.get('title', '')
        description = product.get('description', '')

        # Get listing ID FIRST (needed for image upload)
        ebay_listing_id = ebay_item.get('ebay_listing_id') or ebay_item.get('listingId')
        ebay_offer_id = ebay_item.get('ebay_offer_id') or ebay_item.get('offerId')

        # Process image: download from eBay, compress, upload to Cloudinary
        # Use ebay_listing_id as public_id to prevent image mix-ups
        images = product.get('imageUrls', [])
        item_thumb = None
        if images and process_images:
            from qventory.helpers.image_processor import download_and_upload_image
            ebay_image_url = images[0]
            log_inv(f"Processing image for: {title[:50]}")
            item_thumb = download_and_upload_image(
                ebay_image_url,
                target_size_kb=2,
                max_dimension=400,
                public_id=ebay_listing_id  # Use listing ID as unique identifier
            )
            if not item_thumb:
                log_inv(f"Failed to process image, using original URL")
                item_thumb = ebay_image_url  # Fallback to original URL
        elif images:
            item_thumb = images[0]  # Use original URL if not processing

        # Get SKU (Custom Label from Trading API uses Item.SKU)
        sku = ebay_item.get('sku', '')

        # Get availability
        availability = ebay_item.get('availability', {})
        shipToLocationAvailability = availability.get('shipToLocationAvailability', {})
        quantity = shipToLocationAvailability.get('quantity', 0)

        # Get condition
        condition = ebay_item.get('condition', 'USED_EXCELLENT')

        # Always store eBay Custom SKU as location_code (location only; not a matching key)
        location_components = {}
        location_code = sku or None
        if sku and is_valid_location_code(sku):
            log_inv(f"Detected valid location code in eBay SKU: {sku}")
            location_components = parse_location_code(sku)
        elif sku:
            log_inv(f"eBay SKU '{sku}' is not a valid location code format (stored as location_code)")

        return {
            'title': title,
            'description': description,
            'item_thumb': item_thumb,
            'ebay_sku': sku,
            'quantity': quantity,
            'condition': condition,
            'ebay_listing_id': ebay_listing_id,
            'ebay_offer_id': ebay_offer_id,
            'ebay_url': ebay_item.get('ebay_url') or (f"https://www.ebay.com/itm/{ebay_listing_id}" if ebay_listing_id else None),
            'item_price': ebay_item.get('item_price', 0),
            'location_code': location_code,
            'location_A': location_components.get('A'),
            'location_B': location_components.get('B'),
            'location_S': location_components.get('S'),
            'location_C': location_components.get('C'),
            'variation_skus': ebay_item.get('variation_skus', []),
            'listing_start_time': ebay_item.get('listing_start_time'),
            'listing_end_time': ebay_item.get('listing_end_time'),
            'ebay_item_data': ebay_item
        }


def sync_location_to_ebay_sku(user_id, ebay_listing_id, location_code):
    """
    Sync Qventory location code to eBay Custom SKU field using Trading API

    Args:
        user_id: Qventory user ID
        ebay_listing_id: eBay Item ID
        location_code: Location code from Qventory (e.g., "A1-B2-S3-C4")

    Returns:
        bool: True if successful, False otherwise
    """
    log_inv(f"Syncing location '{location_code}' to eBay listing {ebay_listing_id}")

    access_token = get_user_access_token(user_id)
    if not access_token:
        log_inv("No access token available")
        return False

    app_id = os.environ.get('EBAY_CLIENT_ID')

    # Trading API endpoint
    if EBAY_ENV == 'production':
        trading_url = "https://api.ebay.com/ws/api.dll"
    else:
        trading_url = "https://api.sandbox.ebay.com/ws/api.dll"

    # Build XML request for ReviseItem (update Custom SKU)
    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{ebay_listing_id}</ItemID>
    <SKU>{location_code}</SKU>
  </Item>
</ReviseItemRequest>'''

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
        'X-EBAY-API-CALL-NAME': 'ReviseItem',
        'X-EBAY-API-APP-NAME': app_id,
        'Content-Type': 'text/xml'
    }

    try:
        response = requests.post(trading_url, data=xml_request, headers=headers, timeout=30)
        log_inv(f"Sync response status: {response.status_code}")

        if response.status_code != 200:
            log_inv(f"Sync error: {response.text[:500]}")
            return False

        # Parse XML response
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.content)
        ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}

        # Check for errors
        ack = root.find('ebay:Ack', ns)
        if ack is not None and ack.text in ['Success', 'Warning']:
            log_inv(f"Successfully synced location to eBay listing {ebay_listing_id}")
            return True
        else:
            errors = root.findall('.//ebay:Errors', ns)
            for error in errors:
                error_msg = error.find('ebay:LongMessage', ns)
                if error_msg is not None:
                    log_inv(f"eBay error: {error_msg.text}")
            return False

    except Exception as e:
        log_inv(f"Exception syncing to eBay: {str(e)}")
        return False


def parse_ebay_offer(ebay_offer):
    """
    Parse eBay offer (listing) to get pricing and listing URL

    Args:
        ebay_offer: eBay offer dict from API

    Returns:
        dict with price, listing URL, etc.
    """
    # Get pricing
    pricing_summary = ebay_offer.get('pricingSummary', {})
    price_value = pricing_summary.get('price', {}).get('value', 0)

    # Get listing ID
    listing_id = ebay_offer.get('listingId')
    offer_id = ebay_offer.get('offerId')

    # Construct listing URL
    listing_url = None
    if listing_id:
        listing_url = f"https://www.ebay.com/itm/{listing_id}"

    # Get status
    status = ebay_offer.get('status', 'UNKNOWN')

    # Get SKU
    sku = ebay_offer.get('sku', '')

    return {
        'item_price': float(price_value) if price_value else None,
        'ebay_url': listing_url,
        'ebay_listing_id': listing_id,
        'ebay_offer_id': offer_id,
        'listing_status': status,
        'ebay_sku': sku
    }


def parse_offer_to_item_data(ebay_offer):
    """
    Convert an eBay offer payload into a normalized structure consumed by sync flows.

    Args:
        ebay_offer (dict): Raw offer returned by eBay's Inventory API.

    Returns:
        dict: Flattened offer metadata (price, URL, quantity, raw payload).
    """
    parsed_offer = parse_ebay_offer(ebay_offer)

    product = ebay_offer.get('product') or {}
    quantity = ebay_offer.get('availableQuantity')
    if isinstance(quantity, dict):
        quantity = quantity.get('quantity')
    if quantity is None:
        quantity = ebay_offer.get('quantityLimitPerBuyer')
    if quantity is None:
        availability = ebay_offer.get('listingPolicies', {}).get('fulfillmentPolicies', {})
        if isinstance(availability, dict):
            quantity = availability.get('quantity', 0)

    parsed_offer.update({
        'title': product.get('title'),
        'description': product.get('description'),
        'item_quantity': quantity if quantity is not None else 0,
        'raw_offer': ebay_offer
    })
    return parsed_offer


def fetch_ebay_inventory_offers(user_id, limit=200, offset=0):
    """
    Wrapper around get_active_listings that returns a friendly payload with parsed offers.

    Args:
        user_id (int): Qventory user ID.
        limit (int): Max records per request.
        offset (int): Pagination offset.

    Returns:
        dict: {
            'success': bool,
            'offers': list[dict],
            'total': int,
            'limit': int,
            'offset': int,
            'error': str (optional)
        }
    """
    try:
        listings = get_active_listings(user_id, limit=limit, offset=offset)
        raw_offers = listings.get('offers', []) or []
        parsed_offers = [parse_offer_to_item_data(offer) for offer in raw_offers]

        return {
            'success': True,
            'offers': parsed_offers,
            'total': listings.get('total', len(parsed_offers)),
            'limit': listings.get('limit', limit),
            'offset': listings.get('offset', offset)
        }
    except Exception as exc:
        log_inv(f"ERROR fetching offers: {exc}")
        # Fallback to Trading API (GetMyeBaySelling) which is more permissive
        try:
            log_inv("Falling back to Trading API for active listings...")
            trading_items = get_active_listings_trading_api(
                user_id,
                max_items=limit,
                collect_failures=False
            ) or []

            parsed_offers = []
            for item in trading_items:
                parsed_offers.append({
                    'item_price': item.get('item_price'),
                    'ebay_url': item.get('ebay_url'),
                    'ebay_listing_id': item.get('ebay_listing_id') or item.get('listing_id'),
                    'ebay_offer_id': item.get('ebay_offer_id'),
                    'listing_status': item.get('listing_status', 'PUBLISHED'),
                    'ebay_sku': item.get('ebay_sku') or item.get('sku'),
                    'title': item.get('title'),
                    'description': item.get('description'),
                    'item_quantity': item.get('quantity', 0),
                    'raw_offer': item
                })

            return {
                'success': True,
                'offers': parsed_offers,
                'total': len(parsed_offers),
                'limit': limit,
                'offset': offset
            }
        except Exception as fallback_exc:
            log_inv(f"Trading API fallback failed: {fallback_exc}")
            return {
                'success': False,
                'error': str(exc),
                'offers': [],
                'total': 0,
                'limit': limit,
                'offset': offset
            }


def _normalize_trading_item_to_offer(item):
    """Normalize Trading API item into offer-like payload for sync flows."""
    listing_id = item.get('ebay_listing_id') or item.get('listing_id')
    sku = item.get('sku') or item.get('ebay_sku')
    return {
        'item_price': item.get('item_price'),
        'ebay_url': item.get('ebay_url'),
        'ebay_listing_id': listing_id,
        'ebay_offer_id': item.get('ebay_offer_id'),
        'listing_status': item.get('listing_status', 'ACTIVE'),
        'ebay_sku': sku,
        'title': item.get('title'),
        'description': item.get('description'),
        'item_quantity': item.get('quantity', 0),
        'raw_offer': item
    }


def fetch_active_listings_snapshot(user_id, limit=200, max_pages=50, max_items=5000):
    """
    Fetch a complete snapshot of active listings using Offers API + Trading fallback.

    Returns:
        dict: {
            'success': bool,
            'offers': list[dict],
            'total': int,
            'sources': list[str],
            'can_mark_inactive': bool,
            'error': str (optional)
        }
    """
    offers = []
    total_from_api = None
    offset = 0
    page_number = 1
    sources = []

    while True:
        result = fetch_ebay_inventory_offers(user_id, limit=limit, offset=offset)
        if not result['success']:
            return result

        sources = sources or ['offers_api']
        page_offers = result.get('offers', []) or []
        total_from_api = result.get('total') or total_from_api or len(page_offers)
        offers.extend(page_offers)

        if len(page_offers) < limit:
            break
        if total_from_api and len(offers) >= total_from_api:
            break
        if page_number >= max_pages:
            log_inv(f"Offers API pagination hit max pages ({max_pages}); snapshot may be incomplete")
            break

        offset += limit
        page_number += 1

    trading_success = False
    try:
        trading_items = get_active_listings_trading_api(
            user_id,
            max_items=max_items,
            collect_failures=False
        )
        if trading_items:
            trading_success = True
            sources.append('trading_api')
            trading_offers = [_normalize_trading_item_to_offer(item) for item in trading_items]
            offers.extend(trading_offers)
    except Exception as exc:
        log_inv(f"Trading API augmentation failed: {exc}")

    deduped = []
    seen = set()
    for offer in offers:
        listing_id = offer.get('ebay_listing_id')
        sku = offer.get('ebay_sku')
        key = f"id:{listing_id}" if listing_id else f"sku:{sku}" if sku else None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(offer)

    return {
        'success': True,
        'offers': deduped,
        'total': total_from_api or len(deduped),
        'sources': sources,
        'can_mark_inactive': trading_success
    }


def fetch_shipping_fulfillment_details(user_id, fulfillment_href):
    """
    Fetch detailed shipping/tracking info from a fulfillment href

    Args:
        user_id: Qventory user ID
        fulfillment_href: Full URL to shipping_fulfillment endpoint

    Returns:
        dict: Fulfillment details including tracking, shipped date, delivery date
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return None

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    try:
        response = requests.get(fulfillment_href, headers=headers, timeout=10)

        if response.status_code == 200:
            return response.json()
        else:
            log_inv(f"Failed to fetch fulfillment details: {response.status_code}")
            return None

    except Exception as e:
        log_inv(f"Error fetching fulfillment details: {str(e)}")
        return None


def fetch_ebay_orders(user_id, filter_status=None, limit=100):
    """
    Fetch orders from eBay Fulfillment API

    Args:
        user_id: Qventory user ID
        filter_status: Optional. Order statuses to filter locally (NOT_STARTED, IN_PROGRESS, FULFILLED)
        limit: Maximum number of orders to fetch per request

    Returns:
        dict: {
            'success': bool,
            'orders': list of order dicts,
            'error': str (if success=False)
        }
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {
            'success': False,
            'error': 'No eBay access token available. Please connect your eBay account.',
            'orders': []
        }

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    all_orders = []
    offset = 0

    try:
        while True:
            # Build URL with pagination (no filter in API call - we'll filter locally)
            url = f"{EBAY_API_BASE}/sell/fulfillment/v1/order"
            params = {
                'limit': min(limit, 200),  # eBay max is 200
                'offset': offset
            }

            log_inv(f"Fetching eBay orders: {url}, offset={offset}")

            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 401:
                return {
                    'success': False,
                    'error': 'eBay authentication expired. Please reconnect your eBay account.',
                    'orders': []
                }

            if response.status_code != 200:
                log_inv(f"eBay API error: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f'eBay API error: {response.status_code}',
                    'orders': all_orders  # Return what we got so far
                }

            data = response.json()
            orders = data.get('orders', [])

            if not orders:
                break

            all_orders.extend(orders)

            # Check if there are more pages
            total = data.get('total', 0)
            if offset + len(orders) >= total or len(orders) < params['limit']:
                break

            offset += len(orders)

        log_inv(f"Successfully fetched {len(all_orders)} orders from eBay")

        # Apply local filtering if requested
        if filter_status:
            statuses = [s.strip() for s in filter_status.split(',')]
            filtered_orders = [
                order for order in all_orders
                if order.get('orderFulfillmentStatus') in statuses
            ]
            log_inv(f"Filtered to {len(filtered_orders)} orders with status {filter_status}")
            all_orders = filtered_orders

        return {
            'success': True,
            'orders': all_orders,
            'error': None
        }

    except requests.exceptions.Timeout:
        log_inv("eBay API request timed out")
        return {
            'success': False,
            'error': 'Request timed out. Please try again.',
            'orders': all_orders
        }
    except Exception as e:
        log_inv(f"Error fetching eBay orders: {str(e)}")
        return {
            'success': False,
            'error': f'Error: {str(e)}',
            'orders': all_orders
        }


def parse_ebay_order_to_sale(order_data, user_id=None):
    """
    Parse eBay Fulfillment API order data into Sale model format

    Args:
        order_data: Raw order dict from eBay API
        user_id: Optional user ID to fetch detailed fulfillment info

    Returns:
        dict: Sale model compatible dict
    """
    try:
        def extract_money(*candidates):
            for value in candidates:
                if value is None:
                    continue
                if isinstance(value, dict):
                    raw = value.get('value')
                else:
                    raw = value
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    continue
            return None

        # Extract order ID
        order_id = order_data.get('orderId', '')

        # Get line items (eBay orders can have multiple items)
        line_items = order_data.get('lineItems', [])
        if not line_items:
            log_inv(f"⚠️  Order {order_id}: No line items found")
            return None

        # For now, handle first line item (you can extend this to handle multiple)
        line_item = line_items[0]

        # Extract basic info
        title = line_item.get('title', 'Unknown Item')
        sku = line_item.get('sku', '')
        line_item_id = line_item.get('lineItemId', '')
        legacy_item_id = line_item.get('legacyItemId', '')  # eBay listing ID

        # Extract prices
        total = line_item.get('total', {})
        sold_price = float(total.get('value', 0)) if total else 0

        # Extract shipping info
        shipping_detail = line_item.get('deliveryCost', {})
        shipping_cost = float(shipping_detail.get('shippingCost', {}).get('value', 0)) if shipping_detail else 0

        # Extract fee details if eBay provides them
        pricing_summary = order_data.get('pricingSummary', {}) or {}
        line_pricing_summary = line_item.get('pricingSummary', {}) or {}

        marketplace_fee = extract_money(
            pricing_summary.get('totalMarketplaceFee'),
            pricing_summary.get('marketplaceFee'),
            pricing_summary.get('finalValueFee'),
            line_pricing_summary.get('totalMarketplaceFee'),
            line_pricing_summary.get('marketplaceFee'),
            line_pricing_summary.get('finalValueFee')
        )

        payment_processing_fee = extract_money(
            pricing_summary.get('totalPaymentProcessingFee'),
            pricing_summary.get('paymentProcessingFee'),
            line_pricing_summary.get('totalPaymentProcessingFee'),
            line_pricing_summary.get('paymentProcessingFee')
        )

        other_fees = extract_money(
            pricing_summary.get('totalOtherFee'),
            pricing_summary.get('otherFees'),
            line_pricing_summary.get('totalOtherFee'),
            line_pricing_summary.get('otherFees')
        )

        # Extract fulfillment info
        fulfillment_start = order_data.get('fulfillmentStartInstructions', [{}])[0]
        shipping_step = fulfillment_start.get('shippingStep', {})
        shipment = shipping_step.get('shipTo', {})

        # Extract buyer info
        buyer = order_data.get('buyer', {})
        buyer_username = buyer.get('username', '')

        # Extract tracking - eBay provides this in fulfillmentHrefs, not in lineItems
        tracking_number = None
        carrier = shipping_step.get('shippingCarrierCode', '')  # Already extracted above
        shipped_at = None
        delivered_at = None

        # Determine order status and extract tracking
        order_fulfillment_status = order_data.get('orderFulfillmentStatus', '')

        if order_fulfillment_status == 'FULFILLED':
            status = 'shipped'

            # Fallback shipped date
            modified_date_str = order_data.get('lastModifiedDate', '')
            if modified_date_str:
                shipped_at = _parse_ebay_datetime(modified_date_str)
            if not shipped_at:
                shipped_at = _parse_ebay_datetime(order_data.get('creationDate', ''))
            delivered_at = None

            # Try to get detailed fulfillment info if user_id provided
            fulfillment_hrefs = order_data.get('fulfillmentHrefs', [])
            if fulfillment_hrefs and user_id:
                delivered_statuses = {
                    'DELIVERED',
                    'DELIVERY_SUCCESS',
                    'DELIVERED_TO_BUYER',
                    'DELIVERED_TO_CUSTOMER',
                    'DELIVERED_TO_RECIPIENT',
                    'COMPLETED',
                }
                delivery_evidence = False
                last_delivery_hint = None

                for href in fulfillment_hrefs:
                    fulfillment_details = fetch_shipping_fulfillment_details(user_id, href)
                    if not fulfillment_details:
                        continue

                    # Get actual shipped date (overrides fallback)
                    shipped_date_str = fulfillment_details.get('shippedDate', '')
                    if shipped_date_str:
                        shipped_at = _parse_ebay_datetime(shipped_date_str)

                    mark_as_received = fulfillment_details.get('markAsReceived')
                    if mark_as_received:
                        delivery_evidence = True

                    # Extract tracking info from fulfillment details (all line items)
                    line_items = fulfillment_details.get('lineItems', [])
                    for line_item in line_items:
                        shipment_tracking = line_item.get('shipmentTracking', {})
                        if not tracking_number:
                            tracking_number = shipment_tracking.get('trackingNumber', '')

                        delivered_date_str = shipment_tracking.get('actualDeliveryDate', '')
                        if delivered_date_str:
                            delivered_at = _parse_ebay_datetime(delivered_date_str)
                            delivery_evidence = True
                            break

                        tracking_status = (
                            shipment_tracking.get('deliveryStatus')
                            or shipment_tracking.get('status')
                            or shipment_tracking.get('trackingStatus')
                            or shipment_tracking.get('shipmentStatus')
                            or fulfillment_details.get('deliveryStatus')
                            or ''
                        )
                        tracking_status = str(tracking_status).upper()
                        if tracking_status in delivered_statuses:
                            delivery_evidence = True
                            last_delivery_hint = (
                                fulfillment_details.get('actualDeliveryDate')
                                or fulfillment_details.get('lastModifiedDate')
                                or order_data.get('lastModifiedDate')
                            )

                    if delivered_at:
                        break

                if delivery_evidence:
                    if not delivered_at:
                        delivered_at = _parse_ebay_datetime(last_delivery_hint)
                    if delivered_at:
                        status = 'delivered'

            # Fallback: extract tracking from href if API call failed
            if not tracking_number and fulfillment_hrefs:
                href = fulfillment_hrefs[0]
                parts = href.split('/')
                if len(parts) > 0:
                    potential_tracking = parts[-1]
                    # USPS tracking is typically 20-22 digits
                    if potential_tracking.isdigit() and len(potential_tracking) >= 18:
                        tracking_number = potential_tracking

        elif order_fulfillment_status == 'IN_PROGRESS':
            status = 'shipped'
            # Order is in transit, NOT delivered yet
            delivered_at = None

            # Get shipment info
            fulfillment_hrefs = order_data.get('fulfillmentHrefs', [])
            if fulfillment_hrefs and user_id:
                href = fulfillment_hrefs[0]
                fulfillment_details = fetch_shipping_fulfillment_details(user_id, href)

                if fulfillment_details:
                    # Extract tracking and shipped date
                    line_items = fulfillment_details.get('lineItems', [])
                    delivered_statuses = {
                        'DELIVERED',
                        'DELIVERY_SUCCESS',
                        'DELIVERED_TO_BUYER',
                        'DELIVERED_TO_CUSTOMER',
                        'DELIVERED_TO_RECIPIENT',
                        'COMPLETED',
                    }
                    for line_item in line_items:
                        shipment_tracking = line_item.get('shipmentTracking', {})
                        if not tracking_number:
                            tracking_number = shipment_tracking.get('trackingNumber', '')

                        delivered_date_str = shipment_tracking.get('actualDeliveryDate', '')
                        if delivered_date_str:
                            delivered_at = _parse_ebay_datetime(delivered_date_str)
                            status = 'delivered'
                            break

                        tracking_status = (
                            shipment_tracking.get('deliveryStatus')
                            or shipment_tracking.get('status')
                            or shipment_tracking.get('trackingStatus')
                            or shipment_tracking.get('shipmentStatus')
                            or fulfillment_details.get('deliveryStatus')
                            or ''
                        )
                        tracking_status = str(tracking_status).upper()
                        if tracking_status in delivered_statuses:
                            delivered_at = _parse_ebay_datetime(
                                fulfillment_details.get('actualDeliveryDate')
                                or fulfillment_details.get('lastModifiedDate')
                                or order_data.get('lastModifiedDate')
                            )
                            if delivered_at:
                                status = 'delivered'
                            break

                    # Get shipped date
                    shipped_date_str = fulfillment_details.get('shippedDate', '')
                    if shipped_date_str:
                        shipped_at = _parse_ebay_datetime(shipped_date_str)

            # Fallback: extract tracking from href
            if not tracking_number and fulfillment_hrefs:
                href = fulfillment_hrefs[0]
                parts = href.split('/')
                if len(parts) > 0:
                    potential_tracking = parts[-1]
                    if potential_tracking.isdigit() and len(potential_tracking) >= 18:
                        tracking_number = potential_tracking

        else:
            status = 'pending'

        # Get order creation date (fallback to lastModified/shipped/delivered)
        creation_date_str = order_data.get('creationDate', '')
        sold_at = _parse_ebay_datetime(creation_date_str) if creation_date_str else None
        if sold_at is None:
            sold_at = _parse_ebay_datetime(order_data.get('lastModifiedDate', ''))
        if sold_at is None:
            sold_at = shipped_at or delivered_at
        if sold_at is None:
            sold_at = datetime.utcnow()

        return {
            'marketplace': 'ebay',
            'marketplace_order_id': order_id,
            'item_title': title,
            'item_sku': sku,
            'sold_price': sold_price,
            'shipping_cost': shipping_cost,
            'marketplace_fee': marketplace_fee,
            'payment_processing_fee': payment_processing_fee,
            'other_fees': other_fees,
            'buyer_username': buyer_username,
            'ebay_buyer_username': buyer_username,
            'tracking_number': tracking_number,
            'carrier': carrier,
            'shipped_at': shipped_at,
            'delivered_at': delivered_at,
            'status': status,
            'sold_at': sold_at,
            'ebay_transaction_id': line_item_id,
            'ebay_listing_id': legacy_item_id  # For matching with Item.ebay_listing_id
        }

    except Exception as e:
        log_inv(f"Error parsing eBay order: {str(e)}")
        return None


def fetch_ebay_sold_orders(user_id, days_back=None, fulfillment_statuses=None, max_orders=10000, max_history_days=7300):
    """
    Fetch sold orders from eBay and convert them into sale-friendly payloads.

    Args:
        user_id (int): Qventory user ID.
        days_back (int | None): How many days back to look for orders.
        fulfillment_statuses (Iterable[str] or None): Optional list of eBay fulfillment statuses to keep.
        max_orders (int): Max number of orders to fetch per window.
        max_history_days (int): Maximum historical days to scan when days_back is None (default ≈20 years).

    Returns:
        dict: {
            'success': bool,
            'orders': list[dict],
            'error': str (optional),
            'fetched': int,
            'filtered': int
        }
    """
    from datetime import datetime, timedelta

    # Convert days_back to int if it's a string (can happen from form data)
    if days_back is not None:
        try:
            days_back = int(days_back)
        except (TypeError, ValueError):
            days_back = None

    chunk_days = 90  # eBay Fulfillment API comfortably supports 90-day windows
    window_end = datetime.utcnow()

    if days_back is not None and days_back <= 0:
        return {'success': True, 'orders': [], 'error': None, 'fetched': 0, 'filtered': 0}

    max_history = days_back if days_back is not None else max_history_days
    earliest_allowed = window_end - timedelta(days=max_history)

    aggregated_orders = []
    seen_order_ids = set()
    iterations = 0
    empty_windows = 0

    while window_end > earliest_allowed and iterations < 500:
        window_start = max(earliest_allowed, window_end - timedelta(days=chunk_days))

        # Log progress every 5 iterations (approximately every 450 days / 15 months)
        if iterations % 5 == 0:
            years_back = (datetime.utcnow() - window_end).days / 365.25
            log_inv(f"📅 Scanning historical window: {window_start.strftime('%Y-%m-%d')} to {window_end.strftime('%Y-%m-%d')} (≈{years_back:.1f} years back)")
            log_inv(f"   Progress: {len(aggregated_orders)} orders collected so far, iteration {iterations}/500")

        try:
            window_orders = get_ebay_orders(
                user_id,
                max_orders=max_orders,
                start_date=window_start,
                end_date=window_end
            )
        except Exception as exc:
            log_inv(f"ERROR pulling sold orders window {window_start} -> {window_end}: {exc}")
            return {
                'success': False,
                'orders': [],
                'error': str(exc),
                'fetched': len(aggregated_orders),
                'filtered': 0
            }

        new_added = 0
        for order in window_orders:
            order_id = order.get('orderId')
            if order_id and order_id in seen_order_ids:
                continue
            if order_id:
                seen_order_ids.add(order_id)
            aggregated_orders.append(order)
            new_added += 1

        if new_added == 0:
            empty_windows += 1
        else:
            empty_windows = 0

        iterations += 1
        window_end = window_start - timedelta(seconds=1)

        if empty_windows >= 2:
            log_inv("No additional orders found in previous windows; stopping pagination.")
            break

    # Sort orders chronologically (newest first) for deterministic processing
    aggregated_orders.sort(
        key=lambda order: order.get('creationDate') or order.get('lastModifiedDate') or '',
        reverse=False
    )

    allowed_statuses = None
    if fulfillment_statuses:
        allowed_statuses = {status.upper() for status in fulfillment_statuses}

    parsed_orders = []
    for order in aggregated_orders:
        order_status = (order.get('orderFulfillmentStatus') or '').upper()
        if allowed_statuses and order_status not in allowed_statuses:
            continue

        sale_payload = parse_ebay_order_to_sale(order, user_id=user_id)
        if sale_payload:
            parsed_orders.append(sale_payload)

    log_inv(f"Prepared {len(parsed_orders)} sold orders from {len(aggregated_orders)} raw records")

    return {
        'success': True,
        'orders': parsed_orders,
        'error': None,
        'fetched': len(aggregated_orders),
        'filtered': len(parsed_orders)
    }
