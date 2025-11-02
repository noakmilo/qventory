"""
eBay Auto-Relist Functions
Handles withdraw/publish cycle for eBay offers with optional updates

Supports two modes:
1. AUTO: Withdraw -> Publish (no changes)
2. MANUAL: Withdraw -> Update Offer -> Publish (with price/title/description changes)
"""
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from qventory.helpers.ebay_inventory import get_user_access_token
import xml.etree.ElementTree as ET

def log_relist(msg):
    """Helper for logging"""
    print(f"[EBAY_RELIST] {msg}", file=sys.stderr, flush=True)

# Production eBay API endpoints (no sandbox support)
EBAY_API_BASE = "https://api.ebay.com"
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
TRADING_COMPAT_LEVEL = os.environ.get('EBAY_TRADING_COMPAT_LEVEL', '1145')
_XML_NS = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}


# ==================== INVENTORY API FUNCTIONS (Modern) ====================

def withdraw_offer(user_id: int, offer_id: str) -> dict:
    """
    Withdraw (end) an active eBay offer/listing

    Calls: POST /sell/inventory/v1/offer/{offerId}/withdraw

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID

    Returns:
        dict: {'success': bool, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}/withdraw"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    log_relist(f"Withdrawing offer {offer_id}...")

    try:
        response = requests.post(url, headers=headers, timeout=30)

        # 204 No Content = success
        if response.status_code == 204:
            log_relist(f"✓ Offer {offer_id} withdrawn successfully")
            return {
                'success': True,
                'response': {'status': 'withdrawn', 'offer_id': offer_id}
            }

        # Handle errors
        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        log_relist(f"✗ Withdraw failed: {response.status_code} - {error_msg}")

        return {
            'success': False,
            'error': error_msg,
            'error_code': error_data.get('errors', [{}])[0].get('errorId'),
            'response': error_data
        }

    except requests.exceptions.Timeout:
        log_relist(f"✗ Withdraw timeout")
        return {'success': False, 'error': 'Request timeout'}

    except Exception as e:
        log_relist(f"✗ Exception during withdraw: {str(e)}")
        return {'success': False, 'error': str(e)}


def update_offer(user_id: int, offer_id: str, changes: dict) -> dict:
    """
    Update an eBay offer before publishing (price, title, quantity, etc.)

    Calls: PUT /sell/inventory/v1/offer/{offerId}

    Note: You need to provide the FULL offer object with changes.
    This function fetches the current offer, applies changes, and updates.

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID
        changes: Dict with fields to update, e.g.:
            {
                'price': 29.99,
                'quantity': 5
            }

    Returns:
        dict: {'success': bool, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    log_relist(f"Updating offer {offer_id} with changes: {changes}")

    try:
        # Step 1: Get current offer
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')
            log_relist(f"✗ Failed to fetch offer: {error_msg}")
            return {'success': False, 'error': f'Failed to fetch offer: {error_msg}'}

        current_offer = response.json()

        # Step 2: Apply changes to offer object
        if 'price' in changes:
            if 'pricingSummary' not in current_offer:
                current_offer['pricingSummary'] = {}
            current_offer['pricingSummary']['price'] = {
                'value': str(changes['price']),
                'currency': 'USD'
            }

        if 'quantity' in changes:
            current_offer['availableQuantity'] = int(changes['quantity'])

        # Note: title and description are in the Inventory Item, not Offer
        # We'll handle those separately if needed

        # Step 3: Update offer
        log_relist(f"Sending updated offer data...")
        response = requests.put(url, headers=headers, json=current_offer, timeout=30)

        # 204 No Content or 200 OK = success
        if response.status_code in [200, 204]:
            log_relist(f"✓ Offer {offer_id} updated successfully")
            return {
                'success': True,
                'response': current_offer
            }

        # Handle errors
        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        log_relist(f"✗ Update failed: {response.status_code} - {error_msg}")

        return {
            'success': False,
            'error': error_msg,
            'error_code': error_data.get('errors', [{}])[0].get('errorId'),
            'response': error_data
        }

    except Exception as e:
        log_relist(f"✗ Exception during update: {str(e)}")
        return {'success': False, 'error': str(e)}


def update_inventory_item(user_id: int, sku: str, changes: dict) -> dict:
    """
    Update an eBay Inventory Item (title, description, images, etc.)

    Calls: PUT /sell/inventory/v1/inventory_item/{sku}

    Args:
        user_id: Qventory user ID
        sku: Inventory item SKU
        changes: Dict with fields to update, e.g.:
            {
                'title': 'New Title',
                'description': 'New Description'
            }

    Returns:
        dict: {'success': bool, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/inventory_item/{sku}"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    log_relist(f"Updating inventory item {sku} with changes: {list(changes.keys())}")

    try:
        # Step 1: Get current inventory item
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')
            log_relist(f"✗ Failed to fetch inventory item: {error_msg}")
            return {'success': False, 'error': f'Failed to fetch inventory item: {error_msg}'}

        current_item = response.json()

        # Step 2: Apply changes to inventory item object
        if 'title' in changes and changes['title']:
            if 'product' not in current_item:
                current_item['product'] = {}
            current_item['product']['title'] = str(changes['title'])[:80]  # eBay limit

        if 'description' in changes and changes['description']:
            if 'product' not in current_item:
                current_item['product'] = {}
            current_item['product']['description'] = str(changes['description'])

        if 'condition' in changes and changes['condition']:
            current_item['condition'] = str(changes['condition']).upper()

        # Step 3: Update inventory item
        log_relist(f"Sending updated inventory item data...")
        response = requests.put(url, headers=headers, json=current_item, timeout=30)

        # 204 No Content or 200 OK = success
        if response.status_code in [200, 204]:
            log_relist(f"✓ Inventory item {sku} updated successfully")
            return {
                'success': True,
                'response': current_item
            }

        # Handle errors
        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        log_relist(f"✗ Update failed: {response.status_code} - {error_msg}")

        return {
            'success': False,
            'error': error_msg,
            'error_code': error_data.get('errors', [{}])[0].get('errorId'),
            'response': error_data
        }

    except Exception as e:
        log_relist(f"✗ Exception during update: {str(e)}")
        return {'success': False, 'error': str(e)}


def publish_offer(user_id: int, offer_id: str) -> dict:
    """
    Publish (relist) an eBay offer - creates new listing with new ItemID

    Calls: POST /sell/inventory/v1/offer/{offerId}/publish

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID

    Returns:
        dict: {'success': bool, 'listing_id': str, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}/publish"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    log_relist(f"Publishing offer {offer_id}...")

    try:
        response = requests.post(url, headers=headers, timeout=30)

        # 200 OK = success
        if response.status_code == 200:
            data = response.json()
            listing_id = data.get('listingId')
            log_relist(f"✓ Offer {offer_id} published with new listing ID: {listing_id}")

            return {
                'success': True,
                'listing_id': listing_id,
                'response': data
            }

        # Handle errors
        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        log_relist(f"✗ Publish failed: {response.status_code} - {error_msg}")

        return {
            'success': False,
            'error': error_msg,
            'error_code': error_data.get('errors', [{}])[0].get('errorId'),
            'response': error_data
        }

    except Exception as e:
        log_relist(f"✗ Exception during publish: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_offer_details(user_id: int, offer_id: str) -> dict:
    """
    Get current offer details including status, price, quantity

    Calls: GET /sell/inventory/v1/offer/{offerId}

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID

    Returns:
        dict: {'success': bool, 'offer': dict, 'error': str (optional)}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    url = f"{EBAY_API_BASE}/sell/inventory/v1/offer/{offer_id}"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            return {
                'success': True,
                'offer': response.json()
            }

        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        return {
            'success': False,
            'error': error_msg
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


# ==================== TRADING API FUNCTIONS (Legacy) ====================

def end_item_trading_api(user_id: int, item_id: str, reason='NotAvailable') -> dict:
    """
    End (withdraw) an active eBay listing using Trading API (legacy)

    Calls: EndItem (Trading API)

    Args:
        user_id: Qventory user ID
        item_id: eBay Item ID (listing ID)
        reason: EndReasonCodeType - 'NotAvailable', 'LostOrBroken', 'Incorrect', 'OtherListingError'

    Returns:
        dict: {'success': bool, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    app_id = os.environ.get('EBAY_CLIENT_ID')

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<EndItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <EndingReason>{reason}</EndingReason>
</EndItemRequest>'''

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'EndItem',
        'X-EBAY-API-APP-NAME': app_id,
        'Content-Type': 'text/xml'
    }

    log_relist(f"Ending item {item_id} via Trading API (reason: {reason})...")

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)

        if response.status_code != 200:
            log_relist(f"✗ EndItem failed: HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}'}

        root = ET.fromstring(response.content)
        ack = root.find('ebay:Ack', _XML_NS)

        if ack is not None and ack.text in ['Success', 'Warning']:
            end_time = root.find('ebay:EndTime', _XML_NS)
            log_relist(f"✓ Item {item_id} ended successfully")
            return {
                'success': True,
                'response': {
                    'item_id': item_id,
                    'end_time': end_time.text if end_time is not None else None
                }
            }

        # Handle errors
        errors = root.findall('.//ebay:Errors', _XML_NS)
        error_msgs = []
        for error in errors:
            error_msg = error.find('ebay:LongMessage', _XML_NS)
            if error_msg is not None:
                error_msgs.append(error_msg.text)

        error_text = '; '.join(error_msgs) if error_msgs else 'Unknown error'
        log_relist(f"✗ EndItem failed: {error_text}")

        return {
            'success': False,
            'error': error_text
        }

    except Exception as e:
        log_relist(f"✗ Exception during EndItem: {str(e)}")
        return {'success': False, 'error': str(e)}


def relist_item_trading_api(user_id: int, item_id: str, changes: dict = None) -> dict:
    """
    Relist an ended eBay listing using Trading API (legacy)

    Calls: RelistItem (Trading API)

    Args:
        user_id: Qventory user ID
        item_id: eBay Item ID (listing ID) to relist
        changes: Optional dict with fields to update, e.g.:
            {
                'price': 29.99,
                'quantity': 5,
                'title': 'New Title'
            }

    Returns:
        dict: {'success': bool, 'listing_id': str, 'error': str (optional), 'response': dict}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    app_id = os.environ.get('EBAY_CLIENT_ID')

    # Get item from database to preserve location_code (Custom SKU)
    from qventory.models.item import Item
    item = Item.query.filter_by(user_id=user_id, ebay_listing_id=item_id).first()

    # Build Item element with changes
    item_xml_parts = [f'<ItemID>{item_id}</ItemID>']

    # IMPORTANT: Preserve Custom SKU (location_code) during relist
    if item and item.location_code:
        # Escape XML special characters in location_code
        location = str(item.location_code).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        item_xml_parts.append(f'<SKU>{location}</SKU>')
        log_relist(f"  Preserving Custom SKU (location): {item.location_code}")

    if changes:
        if 'price' in changes:
            item_xml_parts.append(f'<StartPrice>{changes["price"]}</StartPrice>')
        if 'quantity' in changes:
            item_xml_parts.append(f'<Quantity>{int(changes["quantity"])}</Quantity>')
        if 'title' in changes:
            # Escape XML special characters
            title = str(changes['title']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            item_xml_parts.append(f'<Title>{title[:80]}</Title>')
        if 'description' in changes:
            desc = str(changes['description']).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            item_xml_parts.append(f'<Description><![CDATA[{desc}]]></Description>')

    item_xml = '\n    '.join(item_xml_parts)

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<RelistItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    {item_xml}
  </Item>
</RelistItemRequest>'''

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'RelistItem',
        'X-EBAY-API-APP-NAME': app_id,
        'Content-Type': 'text/xml'
    }

    log_relist(f"Relisting item {item_id} via Trading API...")
    if changes:
        log_relist(f"  With changes: {list(changes.keys())}")

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)

        if response.status_code != 200:
            log_relist(f"✗ RelistItem failed: HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}'}

        root = ET.fromstring(response.content)
        ack = root.find('ebay:Ack', _XML_NS)

        if ack is not None and ack.text in ['Success', 'Warning']:
            new_item_id = root.find('ebay:ItemID', _XML_NS)
            listing_id = new_item_id.text if new_item_id is not None else None

            log_relist(f"✓ Item relisted successfully with new ID: {listing_id}")

            return {
                'success': True,
                'listing_id': listing_id,
                'response': {
                    'item_id': listing_id,
                    'old_item_id': item_id
                }
            }

        # Handle errors
        errors = root.findall('.//ebay:Errors', _XML_NS)
        error_msgs = []
        for error in errors:
            error_msg = error.find('ebay:LongMessage', _XML_NS)
            if error_msg is not None:
                error_msgs.append(error_msg.text)

        error_text = '; '.join(error_msgs) if error_msgs else 'Unknown error'
        log_relist(f"✗ RelistItem failed: {error_text}")

        return {
            'success': False,
            'error': error_text
        }

    except Exception as e:
        log_relist(f"✗ Exception during RelistItem: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_item_details_trading_api(user_id: int, item_id: str) -> dict:
    """
    Get item details using Trading API (legacy)

    Calls: GetItem (Trading API)

    Args:
        user_id: Qventory user ID
        item_id: eBay Item ID

    Returns:
        dict: {'success': bool, 'item': dict, 'error': str (optional)}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    app_id = os.environ.get('EBAY_CLIENT_ID')

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>'''

    headers = {
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-COMPATIBILITY-LEVEL': TRADING_COMPAT_LEVEL,
        'X-EBAY-API-CALL-NAME': 'GetItem',
        'X-EBAY-API-APP-NAME': app_id,
        'Content-Type': 'text/xml'
    }

    try:
        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)

        if response.status_code != 200:
            return {'success': False, 'error': f'HTTP {response.status_code}'}

        root = ET.fromstring(response.content)
        ack = root.find('ebay:Ack', _XML_NS)

        if ack is not None and ack.text in ['Success', 'Warning']:
            item_elem = root.find('ebay:Item', _XML_NS)

            if item_elem is None:
                return {'success': False, 'error': 'No item element in response'}

            # Extract key fields
            quantity_elem = item_elem.find('ebay:Quantity', _XML_NS)
            sku_elem = item_elem.find('ebay:SKU', _XML_NS)
            title_elem = item_elem.find('ebay:Title', _XML_NS)

            selling_status = item_elem.find('ebay:SellingStatus', _XML_NS)
            current_price = selling_status.find('ebay:CurrentPrice', _XML_NS) if selling_status is not None else None

            item_data = {
                'item_id': item_id,
                'quantity': int(quantity_elem.text) if quantity_elem is not None else 0,
                'sku': sku_elem.text if sku_elem is not None else '',
                'title': title_elem.text if title_elem is not None else '',
                'price': float(current_price.text) if current_price is not None else 0
            }

            return {
                'success': True,
                'item': item_data
            }

        # Handle errors
        errors = root.findall('.//ebay:Errors', _XML_NS)
        error_msgs = []
        for error in errors:
            error_msg = error.find('ebay:LongMessage', _XML_NS)
            if error_msg is not None:
                error_msgs.append(error_msg.text)

        error_text = '; '.join(error_msgs) if error_msgs else 'Unknown error'
        return {'success': False, 'error': error_text}

    except Exception as e:
        return {'success': False, 'error': str(e)}


# ==================== VALIDATION & ORCHESTRATION ====================

def check_recent_orders(user_id: int, sku: str, hours: int) -> dict:
    """
    Check if item has recent orders

    Args:
        user_id: Qventory user ID
        sku: Item SKU
        hours: Look back period in hours

    Returns:
        dict: {'has_recent_orders': bool, 'order_count': int}
    """
    from qventory.models.sale import Sale
    from qventory.extensions import db

    cutoff_time = datetime.utcnow() - timedelta(hours=hours)

    count = db.session.query(Sale).filter(
        Sale.user_id == user_id,
        Sale.item_sku == sku,
        Sale.sold_at >= cutoff_time
    ).count()

    return {
        'has_recent_orders': count > 0,
        'order_count': count
    }


def check_active_returns(user_id: int, sku: str) -> dict:
    """
    Check if item has active returns/refunds

    Args:
        user_id: Qventory user ID
        sku: Item SKU

    Returns:
        dict: {'has_active_returns': bool, 'return_count': int}
    """
    from qventory.models.sale import Sale
    from qventory.extensions import db

    # Check for returned or refunded sales in last 30 days
    cutoff_time = datetime.utcnow() - timedelta(days=30)

    count = db.session.query(Sale).filter(
        Sale.user_id == user_id,
        Sale.item_sku == sku,
        Sale.status.in_(['returned', 'refunded']),
        Sale.updated_at >= cutoff_time
    ).count()

    return {
        'has_active_returns': count > 0,
        'return_count': count
    }


def validate_offer_for_relist(user_id: int, offer_id: str, rule) -> dict:
    """
    Run all safety checks before relisting (Inventory API version)

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID
        rule: AutoRelistRule object with safety settings

    Returns:
        dict: {
            'valid': bool,
            'skip_reason': str (if not valid),
            'offer_details': dict (if valid)
        }
    """
    log_relist(f"Validating offer {offer_id} for relist...")

    # 1. Get offer details
    offer_result = get_offer_details(user_id, offer_id)

    if not offer_result['success']:
        return {
            'valid': False,
            'skip_reason': f"Failed to fetch offer: {offer_result.get('error')}"
        }

    offer = offer_result['offer']
    sku = offer.get('sku')

    # 2. Check quantity if required
    if rule.require_positive_quantity:
        quantity = offer.get('availableQuantity', 0)
        if quantity <= 0:
            log_relist(f"  ⊘ Validation failed: Zero quantity")
            return {
                'valid': False,
                'skip_reason': 'Zero quantity available'
            }

    # 3. Check recent orders
    if rule.min_hours_since_last_order and sku:
        order_check = check_recent_orders(
            user_id,
            sku,
            rule.min_hours_since_last_order
        )

        if order_check['has_recent_orders']:
            log_relist(f"  ⊘ Validation failed: {order_check['order_count']} recent orders")
            return {
                'valid': False,
                'skip_reason': f"{order_check['order_count']} orders in last {rule.min_hours_since_last_order}h"
            }

    # 4. Check active returns
    if rule.check_active_returns and sku:
        return_check = check_active_returns(user_id, sku)

        if return_check['has_active_returns']:
            log_relist(f"  ⊘ Validation failed: Active returns")
            return {
                'valid': False,
                'skip_reason': f"{return_check['return_count']} active returns"
            }

    # All checks passed
    log_relist(f"  ✓ Validation passed")
    return {
        'valid': True,
        'offer_details': offer
    }


def validate_item_for_relist_trading_api(user_id: int, item_id: str, rule) -> dict:
    """
    Run all safety checks before relisting (Trading API version)

    Args:
        user_id: Qventory user ID
        item_id: eBay Item ID
        rule: AutoRelistRule object with safety settings

    Returns:
        dict: {
            'valid': bool,
            'skip_reason': str (if not valid),
            'item_details': dict (if valid)
        }
    """
    log_relist(f"Validating item {item_id} for relist (Trading API)...")

    # 1. Get item details
    item_result = get_item_details_trading_api(user_id, item_id)

    if not item_result['success']:
        return {
            'valid': False,
            'skip_reason': f"Failed to fetch item: {item_result.get('error')}"
        }

    item = item_result['item']
    sku = item.get('sku')

    # 2. Check quantity if required
    if rule.require_positive_quantity:
        quantity = item.get('quantity', 0)
        if quantity <= 0:
            log_relist(f"  ⊘ Validation failed: Zero quantity")
            return {
                'valid': False,
                'skip_reason': 'Zero quantity available'
            }

    # 3. Check recent orders
    if rule.min_hours_since_last_order and sku:
        order_check = check_recent_orders(
            user_id,
            sku,
            rule.min_hours_since_last_order
        )

        if order_check['has_recent_orders']:
            log_relist(f"  ⊘ Validation failed: {order_check['order_count']} recent orders")
            return {
                'valid': False,
                'skip_reason': f"{order_check['order_count']} orders in last {rule.min_hours_since_last_order}h"
            }

    # 4. Check active returns
    if rule.check_active_returns and sku:
        return_check = check_active_returns(user_id, sku)

        if return_check['has_active_returns']:
            log_relist(f"  ⊘ Validation failed: Active returns")
            return {
                'valid': False,
                'skip_reason': f"{return_check['return_count']} active returns"
            }

    # All checks passed
    log_relist(f"  ✓ Validation passed")
    return {
        'valid': True,
        'item_details': item
    }


def execute_relist(user_id: int, rule, apply_changes=False) -> dict:
    """
    Execute complete relist cycle

    Automatically detects if it should use Inventory API or Trading API based on whether
    the rule has a valid offer_id or just a listing_id.

    Args:
        user_id: Qventory user ID
        rule: AutoRelistRule object
        apply_changes: If True, apply pending_changes before publish

    Returns:
        dict: {
            'success': bool,
            'new_listing_id': str (if success),
            'error': str (if failed),
            'skip_reason': str (if skipped),
            'old_listing_id': str,
            'details': dict with API responses
        }
    """
    from qventory.extensions import db

    # Determine which API to use
    # If offer_id looks like a listing ID (numeric, long), use Trading API
    # If offer_id is a proper UUID/hash, use Inventory API
    use_trading_api = False

    if rule.offer_id and rule.offer_id.isdigit() and len(rule.offer_id) >= 10:
        # Looks like a listing ID (e.g., 376573575653)
        use_trading_api = True
        log_relist(f"=== Starting relist for listing {rule.offer_id} (Trading API) ===")
    else:
        # Looks like an offer ID (UUID format)
        log_relist(f"=== Starting relist for offer {rule.offer_id} (Inventory API) ===")

    log_relist(f"Mode: {rule.mode}, Apply changes: {apply_changes}")

    if use_trading_api:
        return execute_relist_trading_api(user_id, rule, apply_changes)
    else:
        return execute_relist_inventory_api(user_id, rule, apply_changes)


def execute_relist_inventory_api(user_id: int, rule, apply_changes=False) -> dict:
    """
    Execute relist using Inventory API: withdraw -> [update] -> publish

    Args:
        user_id: Qventory user ID
        rule: AutoRelistRule object
        apply_changes: If True, apply pending_changes before publish

    Returns:
        dict with success status and details
    """
    from qventory.extensions import db

    result = {
        'success': False,
        'details': {}
    }

    # Step 1: Validate
    validation = validate_offer_for_relist(user_id, rule.offer_id, rule)

    if not validation['valid']:
        log_relist(f"  ⊘ Validation failed: {validation['skip_reason']}")
        result['skip_reason'] = validation['skip_reason']
        return result

    offer = validation['offer_details']
    old_listing_id = offer.get('listingId')
    result['old_listing_id'] = old_listing_id

    # Step 2: Withdraw
    log_relist(f"  → Step 1/3: Withdrawing offer...")
    withdraw_result = withdraw_offer(user_id, rule.offer_id)
    result['details']['withdraw'] = withdraw_result

    if not withdraw_result['success']:
        log_relist(f"  ✗ Withdraw failed: {withdraw_result.get('error')}")
        result['error'] = f"Withdraw failed: {withdraw_result.get('error')}"
        return result

    # Wait between withdraw and update/publish
    delay = rule.withdraw_publish_delay_seconds or 30
    log_relist(f"  ⏱ Waiting {delay} seconds...")
    time.sleep(delay)

    # Step 3: Update offer/inventory if changes requested
    log_relist(f"  DEBUG: apply_changes={apply_changes}, rule.pending_changes={rule.pending_changes}")
    if apply_changes and rule.pending_changes:
        changes = rule.pending_changes
        log_relist(f"  → Step 2/3: Applying changes: {list(changes.keys())}")
        log_relist(f"  DEBUG: Full changes dict: {changes}")

        # Update price and/or quantity (Offer level)
        if 'price' in changes or 'quantity' in changes:
            offer_changes = {}
            if 'price' in changes:
                offer_changes['price'] = changes['price']
                log_relist(f"  DEBUG: Setting offer price to ${changes['price']}")
            if 'quantity' in changes:
                offer_changes['quantity'] = changes['quantity']

            log_relist(f"  DEBUG: About to call update_offer with: {offer_changes}")
            update_result = update_offer(user_id, rule.offer_id, offer_changes)
            result['details']['update_offer'] = update_result

            if not update_result['success']:
                log_relist(f"  ⚠ Offer update failed: {update_result.get('error')}")
                # Continue anyway - not critical
            else:
                log_relist(f"  DEBUG: Offer update succeeded!")

        # Update title/description/condition (Inventory Item level)
        if any(k in changes for k in ['title', 'description', 'condition']):
            if rule.sku:
                item_changes = {}
                if 'title' in changes:
                    item_changes['title'] = changes['title']
                if 'description' in changes:
                    item_changes['description'] = changes['description']
                if 'condition' in changes:
                    item_changes['condition'] = changes['condition']

                update_item_result = update_inventory_item(user_id, rule.sku, item_changes)
                result['details']['update_inventory'] = update_item_result

                if not update_item_result['success']:
                    log_relist(f"  ⚠ Inventory item update failed: {update_item_result.get('error')}")
                    # Continue anyway

        # Small delay after updates
        log_relist(f"  ⏱ Waiting 5 seconds after updates...")
        time.sleep(5)

    # Step 4: Publish
    log_relist(f"  → Step 3/3: Publishing offer...")
    publish_result = publish_offer(user_id, rule.offer_id)
    result['details']['publish'] = publish_result

    if not publish_result['success']:
        log_relist(f"  ✗ Publish failed: {publish_result.get('error')}")
        result['error'] = f"Publish failed: {publish_result.get('error')}"
        return result

    # Success!
    new_listing_id = publish_result['listing_id']
    log_relist(f"  ✓ SUCCESS! New listing ID: {new_listing_id}")

    result['success'] = True
    result['new_listing_id'] = new_listing_id

    return result


def execute_relist_trading_api(user_id: int, rule, apply_changes=False) -> dict:
    """
    Execute relist using Trading API: EndItem -> RelistItem

    Args:
        user_id: Qventory user ID
        rule: AutoRelistRule object
        apply_changes: If True, apply pending_changes in RelistItem call

    Returns:
        dict with success status and details
    """
    from qventory.extensions import db

    item_id = rule.offer_id  # For Trading API, this is actually the listing ID

    result = {
        'success': False,
        'details': {},
        'old_listing_id': item_id
    }

    # Step 1: Validate
    validation = validate_item_for_relist_trading_api(user_id, item_id, rule)

    if not validation['valid']:
        log_relist(f"  ⊘ Validation failed: {validation['skip_reason']}")
        result['skip_reason'] = validation['skip_reason']
        return result

    item = validation['item_details']

    # Step 2: End Item
    log_relist(f"  → Step 1/2: Ending item...")
    end_result = end_item_trading_api(user_id, item_id, reason='NotAvailable')
    result['details']['end_item'] = end_result

    if not end_result['success']:
        error_msg = str(end_result.get('error', '')).lower()

        # Idempotency: If item is already closed (from previous attempt), continue
        if 'already been closed' in error_msg or 'already closed' in error_msg:
            log_relist(f"  ⚠ Item already closed (likely from previous attempt), continuing to relist...")
            # Don't return - continue to relist step
        else:
            # Real error, abort
            log_relist(f"  ✗ EndItem failed: {end_result.get('error')}")
            result['error'] = f"EndItem failed: {end_result.get('error')}"
            return result

    # Wait between end and relist
    delay = rule.withdraw_publish_delay_seconds or 30
    log_relist(f"  ⏱ Waiting {delay} seconds...")
    time.sleep(delay)

    # Step 3: Relist Item (with optional changes)
    log_relist(f"  → Step 2/2: Relisting item...")
    log_relist(f"  DEBUG: apply_changes={apply_changes}, rule.pending_changes={rule.pending_changes}")

    changes = None
    if apply_changes and rule.pending_changes:
        changes = rule.pending_changes
        log_relist(f"  With changes: {list(changes.keys())}")
        log_relist(f"  DEBUG: Full changes dict for Trading API: {changes}")

    relist_result = relist_item_trading_api(user_id, item_id, changes)
    result['details']['relist_item'] = relist_result

    if not relist_result['success']:
        log_relist(f"  ✗ RelistItem failed: {relist_result.get('error')}")
        result['error'] = f"RelistItem failed: {relist_result.get('error')}"
        return result

    # Success!
    new_listing_id = relist_result['listing_id']
    log_relist(f"  ✓ SUCCESS! New listing ID: {new_listing_id}")

    result['success'] = True
    result['new_listing_id'] = new_listing_id

    return result


# ==================== SALE DETECTION & LISTING ID HELPERS ====================

def check_item_sold_in_fulfillment(user_id: int, listing_id: str) -> bool:
    """
    Check if a listing ID exists in the sales/fulfillment database
    indicating the item has been sold

    Args:
        user_id: Qventory user ID
        listing_id: eBay listing ID to check

    Returns:
        bool: True if item has been sold, False otherwise
    """
    if not listing_id:
        return False

    try:
        from qventory.models.sale import Sale
        from sqlalchemy import or_

        # Check if this listing_id appears in sales table
        # with either shipped_at or delivered_at populated
        sale = Sale.query.filter_by(
            user_id=user_id
        ).filter(
            or_(
                Sale.marketplace_order_id == listing_id,
                Sale.ebay_transaction_id == listing_id
            )
        ).filter(
            or_(
                Sale.delivered_at.isnot(None),
                Sale.shipped_at.isnot(None)
            )
        ).first()

        if sale:
            log_relist(f"✓ Listing {listing_id} found in fulfillment DB - item SOLD")
            return True

        log_relist(f"  Listing {listing_id} not found in sales - item still active")
        return False

    except Exception as e:
        log_relist(f"✗ Error checking sale status: {str(e)}")
        # On error, assume not sold to avoid stopping rules incorrectly
        return False


def get_new_listing_id_from_offer(user_id: int, offer_id: str) -> str:
    """
    Get the current listing ID from an offer
    Used after publish to get the new listing ID

    Args:
        user_id: Qventory user ID
        offer_id: eBay offer ID

    Returns:
        str: Current listing ID, or None if not found
    """
    try:
        result = get_offer_details(user_id, offer_id)

        if not result['success']:
            log_relist(f"✗ Could not fetch offer details: {result.get('error')}")
            return None

        offer = result.get('offer', {})
        listing_id = offer.get('listingId')

        if listing_id:
            log_relist(f"✓ Retrieved listing ID: {listing_id}")
        else:
            log_relist(f"  No listing ID found in offer {offer_id}")

        return listing_id

    except Exception as e:
        log_relist(f"✗ Error getting listing ID: {str(e)}")
        return None
