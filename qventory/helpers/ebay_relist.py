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

def log_relist(msg):
    """Helper for logging"""
    print(f"[EBAY_RELIST] {msg}", file=sys.stderr, flush=True)

EBAY_ENV = os.environ.get('EBAY_ENV', 'production')
EBAY_API_BASE = "https://api.ebay.com" if EBAY_ENV == 'production' else "https://api.sandbox.ebay.com"


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
            return {'success': True, 'offer': response.json()}

        error_data = response.json() if response.text else {}
        error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')

        return {'success': False, 'error': error_msg}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def check_recent_orders(user_id: int, sku: str, hours: int = 48) -> dict:
    """
    Check if there are recent orders for this SKU

    Args:
        user_id: Qventory user ID
        sku: Item SKU
        hours: Hours to look back

    Returns:
        dict: {'has_recent_orders': bool, 'order_count': int, 'orders': list}
    """
    from qventory.models.sale import Sale
    from qventory.extensions import db

    cutoff_time = datetime.utcnow() - timedelta(hours=hours)

    orders = db.session.query(Sale).filter(
        Sale.user_id == user_id,
        Sale.item_sku == sku,
        Sale.sold_at >= cutoff_time,
        Sale.status.in_(['pending', 'paid', 'shipped'])
    ).all()

    return {
        'has_recent_orders': len(orders) > 0,
        'order_count': len(orders),
        'orders': [{'id': o.id, 'sold_at': o.sold_at, 'status': o.status} for o in orders]
    }


def check_active_returns(user_id: int, sku: str) -> dict:
    """
    Check if there are active returns for this SKU

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
    Run all safety checks before relisting

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


def execute_relist(user_id: int, rule, apply_changes=False) -> dict:
    """
    Execute complete relist cycle: withdraw -> [update] -> publish

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

    log_relist(f"=== Starting relist for offer {rule.offer_id} ===")
    log_relist(f"Mode: {rule.mode}, Apply changes: {apply_changes}")

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
    if apply_changes and rule.pending_changes:
        changes = rule.pending_changes
        log_relist(f"  → Step 2/3: Applying changes: {list(changes.keys())}")

        # Update price and/or quantity (Offer level)
        if 'price' in changes or 'quantity' in changes:
            offer_changes = {}
            if 'price' in changes:
                offer_changes['price'] = changes['price']
            if 'quantity' in changes:
                offer_changes['quantity'] = changes['quantity']

            update_result = update_offer(user_id, rule.offer_id, offer_changes)
            result['details']['update_offer'] = update_result

            if not update_result['success']:
                log_relist(f"  ⚠ Offer update failed: {update_result.get('error')}")
                # Continue anyway - not critical

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
