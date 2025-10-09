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

    params = {
        'limit': min(limit, 200),
        'offset': offset
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

        if len(all_items) >= result['total']:
            break

        offset += limit

    # If Inventory API returned 0 items, try Offers API (for traditional listings)
    if len(all_items) == 0:
        log_inv("Inventory API returned 0 items, trying Offers API for traditional listings...")

        try:
            offset = 0
            while len(all_items) < max_items:
                result = get_active_listings(user_id, limit=limit, offset=offset)
                offers = result['offers']

                log_inv(f"Offers API returned {len(offers)} offers (total: {result['total']})")

                if not offers:
                    break

                # Convert offers to inventory-like format
                for offer in offers:
                    # Get SKU from offer
                    sku = offer.get('sku', '')

                    # Extract listing data from offer
                    listing_id = offer.get('listingId')
                    pricing = offer.get('pricingSummary', {})
                    price_value = pricing.get('price', {}).get('value', 0)

                    # Get quantity available
                    quantity_limit = offer.get('quantityLimitPerBuyer', 0)
                    available_quantity = offer.get('availableQuantity', 0)

                    # Try to get listing details if available
                    listing = offer.get('listing', {})

                    # Build item data structure similar to inventory items
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
                        'source': 'offers_api'  # Mark as coming from offers API
                    }

                    all_items.append(item_data)

                if len(all_items) >= result['total']:
                    break

                offset += limit

            log_inv(f"Offers API fallback complete: fetched {len(all_items)} offers")

        except Exception as e:
            log_inv(f"ERROR in Offers API fallback: {str(e)}")

            # Third fallback: Try Browse API with seller search
            log_inv("Offers API failed, trying Browse API with seller search...")
            try:
                browse_items = get_seller_listings_browse_api(user_id, max_items=max_items)
                if browse_items:
                    log_inv(f"Browse API returned {len(browse_items)} items")
                    return browse_items
            except Exception as browse_error:
                log_inv(f"ERROR in Browse API fallback: {str(browse_error)}")

            # Fourth fallback: Try Trading API GetMyeBaySelling for active listings
            log_inv("Browse API failed, trying Trading API GetMyeBaySelling...")
            try:
                trading_items = get_active_listings_trading_api(user_id, max_items=max_items)
                if trading_items:
                    log_inv(f"Trading API returned {len(trading_items)} active listings")
                    return trading_items
            except Exception as trading_error:
                log_inv(f"ERROR in Trading API fallback: {str(trading_error)}")

            # Return empty if all APIs fail
            return []

    return all_items[:max_items]


def get_ebay_orders(user_id, days_back=None, max_orders=5000):
    """
    Get completed orders from eBay Fulfillment API with pagination

    Args:
        user_id: Qventory user ID
        days_back: How many days back to fetch orders (None = lifetime, all orders)
        max_orders: Maximum orders to fetch (default 5000)

    Returns:
        list of order dicts with sale information
    """
    from datetime import datetime, timedelta

    if days_back:
        log_inv(f"Getting eBay orders for user {user_id} (last {days_back} days)")
    else:
        log_inv(f"Getting ALL eBay orders for user {user_id} (lifetime)")

    access_token = get_user_access_token(user_id)
    if not access_token:
        raise Exception("No valid eBay access token available")

    url = f"{EBAY_API_BASE}/sell/fulfillment/v1/order"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    # Build filter
    if days_back:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days_back)
        date_from = start_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        date_to = end_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        filter_param = f'creationdate:[{date_from}..{date_to}]'
        log_inv(f"Fetching orders from {date_from} to {date_to}")
    else:
        # No date filter = all orders lifetime
        filter_param = None
        log_inv(f"Fetching ALL orders (no date filter)")

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


def get_active_listings_trading_api(user_id, max_items=1000):
    """
    Get active listings using Trading API (legacy but reliable)
    Uses GetMyeBaySelling call which works with all listing types

    Args:
        user_id: Qventory user ID
        max_items: Maximum items to fetch (supports pagination for 200+)

    Returns:
        list of items in normalized format
    """
    log_inv(f"Attempting Trading API GetMyeBaySelling for user {user_id}")

    access_token = get_user_access_token(user_id)
    if not access_token:
        log_inv("No access token available")
        return []

    import os
    app_id = os.environ.get('EBAY_CLIENT_ID')

    # Trading API endpoint
    if EBAY_ENV == 'production':
        trading_url = "https://api.ebay.com/ws/api.dll"
    else:
        trading_url = "https://api.sandbox.ebay.com/ws/api.dll"

    import xml.etree.ElementTree as ET
    ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}

    all_items = []
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
            'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
            'X-EBAY-API-CALL-NAME': 'GetMyeBaySelling',
            'X-EBAY-API-APP-NAME': app_id,
            'Content-Type': 'text/xml'
        }

        log_inv(f"Calling Trading API: {trading_url}")
        response = requests.post(trading_url, data=xml_request, headers=headers, timeout=30)
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

                    # Price
                    selling_status = item_elem.find('ebay:SellingStatus', ns)
                    current_price = selling_status.find('ebay:CurrentPrice', ns) if selling_status is not None else None
                    price = float(current_price.text) if current_price is not None else 0

                    # Quantity
                    quantity_elem = item_elem.find('ebay:Quantity', ns)
                    quantity = int(quantity_elem.text) if quantity_elem is not None else 1

                    # SKU
                    sku_elem = item_elem.find('ebay:SKU', ns)
                    sku = sku_elem.text if sku_elem is not None else ''

                    # Image
                    picture_details = item_elem.find('ebay:PictureDetails', ns)
                    image_url = None
                    if picture_details is not None:
                        gallery_url = picture_details.find('ebay:GalleryURL', ns)
                        if gallery_url is not None:
                            image_url = gallery_url.text

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
                        'source': 'trading_api'
                    }
                    all_items.append(normalized)
                    items_in_page += 1

                except Exception as e:
                    # Log which item failed
                    try:
                        failed_id = item_elem.find('ebay:ItemID', ns)
                        failed_title = item_elem.find('ebay:Title', ns)
                        log_inv(f"❌ Error parsing item ID={failed_id.text if failed_id is not None else 'Unknown'}, Title={failed_title.text[:50] if failed_title is not None else 'Unknown'}: {str(e)}")
                    except:
                        log_inv(f"❌ Error parsing item (couldn't extract ID/title): {str(e)}")
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
    if 'total_entries' in locals() and len(all_items) < total_entries:
        missing = total_entries - len(all_items)
        log_inv(f"  ⚠️  MISSING {missing} items ({missing/total_entries*100:.1f}%)")
        log_inv(f"  Possible causes:")
        log_inv(f"    - Items failed to parse (check ❌ errors above)")
        log_inv(f"    - eBay API returned incomplete data")
        log_inv(f"    - Items don't meet API filter criteria")
    log_inv(f"=" * 60)

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
    import os
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

        # Process image: download from eBay, compress, upload to Cloudinary
        item_thumb = None
        if images and process_images:
            from qventory.helpers.image_processor import download_and_upload_image
            ebay_image_url = images[0]
            log_inv(f"Processing image for: {title[:50]}")
            item_thumb = download_and_upload_image(ebay_image_url, target_size_kb=2, max_dimension=400)
            if not item_thumb:
                log_inv(f"Failed to process image, using original URL")
                item_thumb = ebay_image_url  # Fallback to original URL
        elif images:
            item_thumb = images[0]  # Use original URL if not processing
        sku = ebay_item.get('sku', '')
        availability = ebay_item.get('availability', {})
        quantity = availability.get('shipToLocationAvailability', {}).get('quantity', 0)
        condition = ebay_item.get('condition', 'USED_EXCELLENT')

        # Get additional offer-specific data
        ebay_listing_id = ebay_item.get('ebay_listing_id')
        ebay_url = ebay_item.get('ebay_url')
        item_price = ebay_item.get('item_price', 0)

        # Check if eBay Custom SKU is a valid Qventory location code
        location_components = {}
        location_code = None
        if sku and is_valid_location_code(sku):
            log_inv(f"Detected valid location code in eBay SKU: {sku}")
            location_components = parse_location_code(sku)
            location_code = sku
        else:
            log_inv(f"eBay SKU '{sku}' is not a valid location code format")

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
            'location_code': location_code,  # Parsed location code if valid
            'location_A': location_components.get('A'),
            'location_B': location_components.get('B'),
            'location_S': location_components.get('S'),
            'location_C': location_components.get('C'),
            'ebay_item_data': ebay_item
        }
    else:
        # Original Inventory API format
        product = ebay_item.get('product', {})
        title = product.get('title', '')
        description = product.get('description', '')

        # Process image: download from eBay, compress, upload to Cloudinary
        images = product.get('imageUrls', [])
        item_thumb = None
        if images and process_images:
            from qventory.helpers.image_processor import download_and_upload_image
            ebay_image_url = images[0]
            log_inv(f"Processing image for: {title[:50]}")
            item_thumb = download_and_upload_image(ebay_image_url, target_size_kb=2, max_dimension=400)
            if not item_thumb:
                log_inv(f"Failed to process image, using original URL")
                item_thumb = ebay_image_url  # Fallback to original URL
        elif images:
            item_thumb = images[0]  # Use original URL if not processing

        # Get SKU
        sku = ebay_item.get('sku', '')

        # Get availability
        availability = ebay_item.get('availability', {})
        shipToLocationAvailability = availability.get('shipToLocationAvailability', {})
        quantity = shipToLocationAvailability.get('quantity', 0)

        # Get condition
        condition = ebay_item.get('condition', 'USED_EXCELLENT')

        # Check if eBay Custom SKU is a valid Qventory location code
        location_components = {}
        location_code = None
        if sku and is_valid_location_code(sku):
            log_inv(f"Detected valid location code in eBay SKU: {sku}")
            location_components = parse_location_code(sku)
            location_code = sku
        else:
            log_inv(f"eBay SKU '{sku}' is not a valid location code format")

        return {
            'title': title,
            'description': description,
            'item_thumb': item_thumb,
            'ebay_sku': sku,
            'quantity': quantity,
            'condition': condition,
            'location_code': location_code,
            'location_A': location_components.get('A'),
            'location_B': location_components.get('B'),
            'location_S': location_components.get('S'),
            'location_C': location_components.get('C'),
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

    import os
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
