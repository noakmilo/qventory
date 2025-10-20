"""
eBay Webhook Helper Functions
Handles signature validation, logging, and utility functions
"""
import sys
import hmac
import hashlib
import base64
import json
from datetime import datetime


def log_webhook(msg):
    """Helper for webhook logging"""
    print(f"[WEBHOOK] {msg}", file=sys.stderr, flush=True)


def validate_ebay_signature(payload: bytes, signature: str, client_secret: str) -> bool:
    """
    Validate eBay webhook signature

    eBay signs webhooks using HMAC-SHA256 with your OAuth client secret.
    The signature is sent in the X-EBAY-SIGNATURE header.

    Args:
        payload: Raw request body (bytes)
        signature: Signature from X-EBAY-SIGNATURE header
        client_secret: Your eBay OAuth client secret

    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not signature or not client_secret:
        log_webhook("⚠️  Missing signature or client secret")
        return False

    try:
        # eBay uses HMAC-SHA256
        expected_signature = hmac.new(
            client_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).digest()

        # eBay sends signature as base64-encoded string
        expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')

        # Compare signatures using constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(signature, expected_signature_b64)

        if is_valid:
            log_webhook("✓ Signature validation passed")
        else:
            log_webhook("✗ Signature validation failed")
            log_webhook(f"  Expected: {expected_signature_b64[:20]}...")
            log_webhook(f"  Received: {signature[:20]}...")

        return is_valid

    except Exception as e:
        log_webhook(f"✗ Signature validation error: {str(e)}")
        return False


def parse_ebay_event(payload: dict) -> dict:
    """
    Parse eBay webhook event payload

    eBay webhook events have this structure:
    {
        "metadata": {
            "topic": "MARKETPLACE_ACCOUNT_DELETION",
            "eventId": "unique-event-id",
            "timestamp": "2025-10-20T10:30:00.000Z"
        },
        "notification": {
            // Event-specific data
        }
    }

    Args:
        payload: Parsed JSON payload from eBay

    Returns:
        dict: Parsed event data with metadata
    """
    try:
        metadata = payload.get('metadata', {})
        notification = payload.get('notification', {})

        # Extract common fields
        event_data = {
            'event_id': metadata.get('eventId'),
            'topic': metadata.get('topic'),
            'timestamp': metadata.get('timestamp'),
            'notification': notification,
            'raw_payload': payload
        }

        # Parse timestamp
        if event_data['timestamp']:
            try:
                event_data['timestamp_dt'] = datetime.fromisoformat(
                    event_data['timestamp'].replace('Z', '+00:00')
                )
            except:
                event_data['timestamp_dt'] = None

        return event_data

    except Exception as e:
        log_webhook(f"✗ Error parsing event payload: {str(e)}")
        return {
            'event_id': None,
            'topic': None,
            'timestamp': None,
            'notification': {},
            'raw_payload': payload,
            'parse_error': str(e)
        }


def get_user_id_from_notification(notification: dict) -> int:
    """
    Extract user_id from notification data

    Different event types may have user identifiers in different places.
    This function attempts to extract the user ID.

    Args:
        notification: The notification object from the webhook payload

    Returns:
        int: User ID if found, None otherwise
    """
    # Try common fields where user ID might be
    # Note: You may need to adjust this based on actual eBay webhook structure

    # Try to get from various possible locations
    user_id = None

    if 'userId' in notification:
        user_id = notification['userId']
    elif 'sellerId' in notification:
        user_id = notification['sellerId']
    elif 'buyerId' in notification:
        user_id = notification['buyerId']

    return user_id


def is_duplicate_event(event_id: str) -> bool:
    """
    Check if we've already received this event

    eBay may send the same event multiple times (at-least-once delivery).
    We need to detect duplicates and ignore them.

    Args:
        event_id: Unique event ID from eBay

    Returns:
        bool: True if this is a duplicate, False if it's new
    """
    from qventory.models.webhook import WebhookEvent

    existing = WebhookEvent.query.filter_by(event_id=event_id).first()
    return existing is not None


def format_webhook_error(error: Exception, context: str = "") -> dict:
    """
    Format error for logging and storage

    Args:
        error: Exception that occurred
        context: Additional context about where error occurred

    Returns:
        dict: Formatted error details
    """
    return {
        'error_type': type(error).__name__,
        'error_message': str(error),
        'context': context,
        'timestamp': datetime.utcnow().isoformat()
    }


def get_webhook_stats(user_id: int) -> dict:
    """
    Get webhook statistics for a user

    Args:
        user_id: User ID

    Returns:
        dict: Statistics about webhooks for this user
    """
    from qventory.models.webhook import WebhookSubscription, WebhookEvent
    from qventory.extensions import db

    # Count subscriptions
    total_subscriptions = WebhookSubscription.query.filter_by(user_id=user_id).count()
    active_subscriptions = WebhookSubscription.query.filter_by(
        user_id=user_id,
        status='ENABLED'
    ).count()

    # Count events
    total_events = WebhookEvent.query.filter_by(user_id=user_id).count()
    pending_events = WebhookEvent.query.filter_by(
        user_id=user_id,
        status='pending'
    ).count()
    failed_events = WebhookEvent.query.filter_by(
        user_id=user_id,
        status='failed'
    ).count()

    # Get recent event
    recent_event = WebhookEvent.query.filter_by(
        user_id=user_id
    ).order_by(WebhookEvent.received_at.desc()).first()

    return {
        'subscriptions': {
            'total': total_subscriptions,
            'active': active_subscriptions
        },
        'events': {
            'total': total_events,
            'pending': pending_events,
            'failed': failed_events
        },
        'last_event_at': recent_event.received_at.isoformat() if recent_event else None
    }


def sanitize_webhook_payload(payload: dict) -> dict:
    """
    Sanitize webhook payload before storing
    Remove sensitive data if any

    Args:
        payload: Raw webhook payload

    Returns:
        dict: Sanitized payload
    """
    # Create a copy to avoid modifying original
    sanitized = payload.copy()

    # List of fields to remove if present (sensitive data)
    sensitive_fields = [
        'password',
        'token',
        'secret',
        'apiKey',
        'api_key',
        'accessToken',
        'access_token'
    ]

    def remove_sensitive(obj):
        """Recursively remove sensitive fields"""
        if isinstance(obj, dict):
            return {
                k: remove_sensitive(v)
                for k, v in obj.items()
                if k not in sensitive_fields
            }
        elif isinstance(obj, list):
            return [remove_sensitive(item) for item in obj]
        else:
            return obj

    return remove_sensitive(sanitized)
