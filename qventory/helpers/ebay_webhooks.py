"""
eBay Notification API Helpers
Manages webhook subscriptions with eBay
"""
import os
import sys
import requests
from datetime import datetime, timedelta
from qventory.helpers.ebay_inventory import get_user_access_token


def log_webhook_api(msg):
    """Helper for webhook API logging"""
    print(f"[EBAY_WEBHOOK_API] {msg}", file=sys.stderr, flush=True)


# eBay Notification API endpoint
EBAY_API_BASE = "https://api.ebay.com"
NOTIFICATION_API_URL = f"{EBAY_API_BASE}/commerce/notification/v1"


def create_webhook_subscription(user_id: int, topic: str, delivery_url: str) -> dict:
    """
    Create a new webhook subscription with eBay

    eBay Notification API: POST /commerce/notification/v1/destination
    Then: POST /commerce/notification/v1/subscription

    Args:
        user_id: Qventory user ID
        topic: Event topic (e.g., 'ITEM_SOLD', 'ITEM_ENDED')
        delivery_url: Your webhook endpoint URL (must be HTTPS)

    Returns:
        dict: {
            'success': bool,
            'subscription_id': str (if success),
            'destination_id': str (if success),
            'expires_at': datetime (if success),
            'error': str (if failed)
        }
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    log_webhook_api(f"Creating subscription for topic: {topic}")
    log_webhook_api(f"Delivery URL: {delivery_url}")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    try:
        # Step 1: Create destination (webhook endpoint)
        # NOTE: eBay validates the endpoint via challenge-response (GET request)
        # before accepting the destination creation
        destination_payload = {
            "name": f"Qventory-{topic}",
            "status": "ENABLED",
            "deliveryConfig": {
                "endpoint": delivery_url
                # Do NOT include verificationToken - eBay uses challenge-response instead
            }
        }

        log_webhook_api("Step 1: Creating destination...")
        log_webhook_api(f"  Payload: {destination_payload}")

        dest_response = requests.post(
            f"{NOTIFICATION_API_URL}/destination",
            headers=headers,
            json=destination_payload,
            timeout=30
        )

        log_webhook_api(f"  Response status: {dest_response.status_code}")
        log_webhook_api(f"  Response body: {dest_response.text[:500]}")

        if dest_response.status_code not in [200, 201]:
            error_data = dest_response.json() if dest_response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {dest_response.status_code}')

            # Log full error details
            log_webhook_api(f"✗ Destination creation failed: {error_msg}")
            log_webhook_api(f"  Full error response: {error_data}")

            return {'success': False, 'error': f'Destination creation failed: {error_msg}'}

        destination = dest_response.json()
        destination_id = destination.get('destinationId')
        log_webhook_api(f"✓ Destination created: {destination_id}")

        # Step 2: Create subscription
        subscription_payload = {
            "topicId": topic,
            "destinationId": destination_id,
            "status": "ENABLED"
        }

        log_webhook_api("Step 2: Creating subscription...")
        sub_response = requests.post(
            f"{NOTIFICATION_API_URL}/subscription",
            headers=headers,
            json=subscription_payload,
            timeout=30
        )

        if sub_response.status_code not in [200, 201]:
            error_data = sub_response.json() if sub_response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {sub_response.status_code}')
            log_webhook_api(f"✗ Subscription creation failed: {error_msg}")
            return {'success': False, 'error': f'Subscription creation failed: {error_msg}'}

        subscription = sub_response.json()
        subscription_id = subscription.get('subscriptionId')

        # eBay subscriptions expire after 7 days
        expires_at = datetime.utcnow() + timedelta(days=7)

        log_webhook_api(f"✓ Subscription created: {subscription_id}")
        log_webhook_api(f"  Expires at: {expires_at}")

        return {
            'success': True,
            'subscription_id': subscription_id,
            'destination_id': destination_id,
            'expires_at': expires_at,
            'response': subscription
        }

    except requests.exceptions.Timeout:
        log_webhook_api("✗ Request timeout")
        return {'success': False, 'error': 'Request timeout'}

    except Exception as e:
        log_webhook_api(f"✗ Exception: {str(e)}")
        return {'success': False, 'error': str(e)}


def renew_webhook_subscription(user_id: int, subscription_id: str) -> dict:
    """
    Renew an existing webhook subscription

    eBay subscriptions expire after 7 days and must be renewed.

    Args:
        user_id: Qventory user ID
        subscription_id: eBay subscription ID to renew

    Returns:
        dict: {
            'success': bool,
            'expires_at': datetime (if success),
            'error': str (if failed)
        }
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    log_webhook_api(f"Renewing subscription: {subscription_id}")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    try:
        # Update subscription to renew it (PUT request resets expiration)
        update_payload = {
            "status": "ENABLED"
        }

        response = requests.put(
            f"{NOTIFICATION_API_URL}/subscription/{subscription_id}",
            headers=headers,
            json=update_payload,
            timeout=30
        )

        if response.status_code not in [200, 204]:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')
            log_webhook_api(f"✗ Renewal failed: {error_msg}")
            return {'success': False, 'error': f'Renewal failed: {error_msg}'}

        # Subscription renewed - expires in 7 days from now
        expires_at = datetime.utcnow() + timedelta(days=7)

        log_webhook_api(f"✓ Subscription renewed")
        log_webhook_api(f"  New expiration: {expires_at}")

        return {
            'success': True,
            'expires_at': expires_at
        }

    except Exception as e:
        log_webhook_api(f"✗ Exception: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_webhook_subscription(user_id: int, subscription_id: str, destination_id: str = None) -> dict:
    """
    Delete a webhook subscription from eBay

    Args:
        user_id: Qventory user ID
        subscription_id: eBay subscription ID to delete
        destination_id: Optional destination ID to delete as well

    Returns:
        dict: {'success': bool, 'error': str (if failed)}
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    log_webhook_api(f"Deleting subscription: {subscription_id}")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    try:
        # Delete subscription
        response = requests.delete(
            f"{NOTIFICATION_API_URL}/subscription/{subscription_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code not in [200, 204]:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')
            log_webhook_api(f"✗ Deletion failed: {error_msg}")
            return {'success': False, 'error': f'Deletion failed: {error_msg}'}

        log_webhook_api(f"✓ Subscription deleted")

        # Optionally delete destination as well
        if destination_id:
            log_webhook_api(f"Deleting destination: {destination_id}")
            dest_response = requests.delete(
                f"{NOTIFICATION_API_URL}/destination/{destination_id}",
                headers=headers,
                timeout=30
            )
            if dest_response.status_code in [200, 204]:
                log_webhook_api(f"✓ Destination deleted")

        return {'success': True}

    except Exception as e:
        log_webhook_api(f"✗ Exception: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_webhook_subscriptions(user_id: int) -> dict:
    """
    Get all webhook subscriptions for a user from eBay

    Args:
        user_id: Qventory user ID

    Returns:
        dict: {
            'success': bool,
            'subscriptions': list of subscription dicts,
            'error': str (if failed)
        }
    """
    access_token = get_user_access_token(user_id)
    if not access_token:
        return {'success': False, 'error': 'No valid eBay access token'}

    log_webhook_api("Fetching all subscriptions from eBay...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }

    try:
        response = requests.get(
            f"{NOTIFICATION_API_URL}/subscription",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get('errors', [{}])[0].get('message', f'HTTP {response.status_code}')
            log_webhook_api(f"✗ Failed to fetch subscriptions: {error_msg}")
            return {'success': False, 'error': error_msg}

        data = response.json()
        subscriptions = data.get('subscriptions', [])

        log_webhook_api(f"✓ Found {len(subscriptions)} subscriptions")

        return {
            'success': True,
            'subscriptions': subscriptions
        }

    except Exception as e:
        log_webhook_api(f"✗ Exception: {str(e)}")
        return {'success': False, 'error': str(e)}


# Available eBay webhook topics
AVAILABLE_TOPICS = {
    # Inventory/Listing events
    'ITEM_SOLD': {
        'category': 'Inventory',
        'description': 'Triggered when an item is sold',
        'priority': 'high'
    },
    'ITEM_ENDED': {
        'category': 'Inventory',
        'description': 'Triggered when a listing ends',
        'priority': 'medium'
    },
    'ITEM_OUT_OF_STOCK': {
        'category': 'Inventory',
        'description': 'Triggered when an item goes out of stock',
        'priority': 'high'
    },
    'ITEM_PRICE_CHANGE': {
        'category': 'Inventory',
        'description': 'Triggered when an item price changes',
        'priority': 'low'
    },

    # Fulfillment events
    'FULFILLMENT_ORDER_SHIPPED': {
        'category': 'Fulfillment',
        'description': 'Triggered when an order is shipped',
        'priority': 'medium'
    },
    'FULFILLMENT_ORDER_DELIVERED': {
        'category': 'Fulfillment',
        'description': 'Triggered when an order is delivered',
        'priority': 'medium'
    },

    # Return/Refund events
    'RETURN_REQUESTED': {
        'category': 'Returns',
        'description': 'Triggered when a buyer requests a return',
        'priority': 'high'
    },
    'RETURN_CLOSED': {
        'category': 'Returns',
        'description': 'Triggered when a return case is closed',
        'priority': 'medium'
    },

    # Account events
    'MARKETPLACE_ACCOUNT_DELETION': {
        'category': 'Account',
        'description': 'Triggered when user deletes their eBay account',
        'priority': 'high'
    }
}


def get_recommended_topics() -> list:
    """
    Get recommended topics for Qventory users

    Returns:
        list: List of recommended topic IDs
    """
    return [
        'ITEM_SOLD',
        'ITEM_ENDED',
        'ITEM_OUT_OF_STOCK',
        'FULFILLMENT_ORDER_SHIPPED',
        'FULFILLMENT_ORDER_DELIVERED'
    ]
