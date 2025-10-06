"""
eBay Inventory API Helper
Functions to fetch and sync inventory from eBay Sell API
"""
import os
import sys
import requests
from datetime import datetime
from qventory.models.marketplace_credential import MarketplaceCredential

def log_inv(msg):
    """Helper function for logging"""
    print(f"[EBAY_INVENTORY] {msg}", file=sys.stderr, flush=True)

EBAY_ENV = os.environ.get('EBAY_ENV', 'production')

if EBAY_ENV == 'production':
    EBAY_API_BASE = "https://api.ebay.com"
else:
    EBAY_API_BASE = "https://api.sandbox.ebay.com"


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

    headers = {
        'Authorization': f'Bearer {access_token[:20]}...',
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
    access_token = get_user_access_token(user_id)
    if not access_token:
        raise Exception("No valid eBay access token available")

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    params = {
        'limit': min(limit, 200),
        'offset': offset
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    return {
        'offers': data.get('offers', []),
        'total': data.get('total', 0),
        'limit': limit,
        'offset': offset
    }


def get_all_inventory(user_id, max_items=1000):
    """
    Get all inventory items (paginated)

    Args:
        user_id: Qventory user ID
        max_items: Maximum total items to fetch

    Returns:
        list of inventory items
    """
    all_items = []
    offset = 0
    limit = 200

    while len(all_items) < max_items:
        result = get_inventory_items(user_id, limit=limit, offset=offset)
        items = result['items']

        if not items:
            break

        all_items.extend(items)

        if len(all_items) >= result['total']:
            break

        offset += limit

    return all_items[:max_items]


def parse_ebay_inventory_item(ebay_item):
    """
    Parse eBay inventory item to Qventory format

    Args:
        ebay_item: eBay inventory item dict from API

    Returns:
        dict with Qventory item fields
    """
    # Get product info
    product = ebay_item.get('product', {})
    title = product.get('title', '')
    description = product.get('description', '')

    # Get image
    images = product.get('imageUrls', [])
    item_thumb = images[0] if images else None

    # Get SKU
    sku = ebay_item.get('sku', '')

    # Get availability
    availability = ebay_item.get('availability', {})
    shipToLocationAvailability = availability.get('shipToLocationAvailability', {})
    quantity = shipToLocationAvailability.get('quantity', 0)

    # Get condition
    condition = ebay_item.get('condition', 'USED_EXCELLENT')

    return {
        'title': title,
        'description': description,
        'item_thumb': item_thumb,
        'ebay_sku': sku,
        'quantity': quantity,
        'condition': condition,
        'ebay_item_data': ebay_item  # Store full data for reference
    }


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
