"""
eBay Webhook Routes
Handles incoming webhook events from eBay
"""
import os
import json
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from qventory.extensions import db
from qventory.models.webhook import WebhookSubscription, WebhookEvent, WebhookProcessingQueue
from qventory.helpers.webhook_helpers import (
    log_webhook,
    validate_ebay_signature,
    parse_ebay_event,
    is_duplicate_event,
    format_webhook_error,
    sanitize_webhook_payload
)

webhook_bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')


@webhook_bp.route('/ebay', methods=['GET', 'POST'])
def ebay_webhook():
    """
    Main eBay webhook endpoint

    Handles two types of requests:
    1. GET with challenge code (eBay verification)
    2. POST with webhook event (actual notifications)
    """
    # === STEP 1: eBay Challenge Response (GET) ===
    if request.method == 'GET':
        return handle_ebay_challenge()

    # === STEP 2: Webhook Event Processing (POST) ===
    return handle_ebay_event()


def handle_ebay_challenge():
    """
    Handle eBay challenge code verification

    When you create a webhook subscription, eBay sends a GET request with
    a challenge code that you must echo back to verify your endpoint.

    Example:
    GET /webhooks/ebay?challenge_code=abc123

    Response should be:
    {"challengeResponse": "abc123"}
    """
    # Log ALL request details for debugging
    log_webhook("="*60)
    log_webhook("EBAY CHALLENGE REQUEST RECEIVED")
    log_webhook(f"  Method: {request.method}")
    log_webhook(f"  URL: {request.url}")
    log_webhook(f"  Query params: {dict(request.args)}")
    log_webhook(f"  Headers: {dict(request.headers)}")
    log_webhook("="*60)

    challenge_code = request.args.get('challenge_code')

    if not challenge_code:
        log_webhook("✗ Challenge request missing challenge_code parameter")
        return jsonify({'error': 'Missing challenge_code parameter'}), 400

    log_webhook(f"✓ Received eBay challenge code: {challenge_code[:50]}...")

    # Echo back the challenge code as required by eBay
    response = {
        'challengeResponse': challenge_code
    }

    log_webhook(f"✓ Sending challenge response: {response}")
    return jsonify(response), 200


def handle_ebay_event():
    """
    Handle incoming eBay webhook event

    Flow:
    1. Validate signature
    2. Parse event payload
    3. Check for duplicates
    4. Store event in database
    5. Queue for processing
    6. Return 200 OK immediately (async processing)
    """
    try:
        # === STEP 1: Get request data ===
        raw_payload = request.get_data()
        signature = request.headers.get('X-EBAY-SIGNATURE', '')
        content_type = request.headers.get('Content-Type', '')

        log_webhook(f"Received webhook event")
        log_webhook(f"  Content-Type: {content_type}")
        log_webhook(f"  Payload size: {len(raw_payload)} bytes")
        log_webhook(f"  Signature: {signature[:20]}...")

        # === STEP 2: Validate signature ===
        client_secret = os.environ.get('EBAY_CLIENT_SECRET')

        if not client_secret:
            log_webhook("✗ EBAY_CLIENT_SECRET not configured")
            return jsonify({'error': 'Server configuration error'}), 500

        # Validate signature
        if not validate_ebay_signature(raw_payload, signature, client_secret):
            log_webhook("✗ Invalid signature - rejecting webhook")
            return jsonify({'error': 'Invalid signature'}), 401

        # === STEP 3: Parse JSON payload ===
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as e:
            log_webhook(f"✗ Invalid JSON payload: {str(e)}")
            return jsonify({'error': 'Invalid JSON'}), 400

        # === STEP 4: Parse eBay event structure ===
        event_data = parse_ebay_event(payload)

        event_id = event_data.get('event_id')
        topic = event_data.get('topic')

        if not event_id or not topic:
            log_webhook("✗ Missing event_id or topic in payload")
            return jsonify({'error': 'Invalid event structure'}), 400

        log_webhook(f"  Event ID: {event_id}")
        log_webhook(f"  Topic: {topic}")

        # === STEP 5: Check for duplicates ===
        if is_duplicate_event(event_id):
            log_webhook(f"  ⊘ Duplicate event - already processed")
            return jsonify({'status': 'duplicate', 'message': 'Event already processed'}), 200

        # === STEP 6: Determine user_id ===
        # For now, we'll need to map this from the subscription or notification
        # This is a placeholder - actual implementation depends on how we track subscriptions
        user_id = get_user_id_from_event(event_data)

        if not user_id:
            log_webhook("⚠️  Could not determine user_id - storing with user_id=NULL for manual review")
            user_id = None  # Placeholder for manual review

        # === STEP 7: Store event in database ===
        webhook_event = WebhookEvent(
            user_id=user_id,
            event_id=event_id,
            topic=topic,
            payload=sanitize_webhook_payload(payload),
            headers={
                'content-type': content_type,
                'signature': signature[:50]  # Store truncated signature for reference
            },
            ebay_timestamp=event_data.get('timestamp_dt'),
            status='pending'
        )

        db.session.add(webhook_event)
        db.session.commit()

        log_webhook(f"  ✓ Event stored with ID: {webhook_event.id}")

        # === STEP 8: Update subscription stats ===
        subscription = WebhookSubscription.query.filter_by(
            user_id=user_id,
            topic=topic,
            status='ENABLED'
        ).first()

        if subscription:
            subscription.mark_event_received()
            webhook_event.subscription_id = subscription.id
            db.session.commit()
            log_webhook(f"  ✓ Updated subscription {subscription.id} stats")

        # === STEP 9: Queue for processing ===
        queue_item = WebhookProcessingQueue(
            event_id=webhook_event.id,
            priority=get_event_priority(topic),
            status='queued'
        )

        db.session.add(queue_item)
        db.session.commit()

        log_webhook(f"  ✓ Queued for processing (priority: {queue_item.priority})")

        # === STEP 10: Trigger async processing ===
        # Import here to avoid circular dependency
        from qventory.tasks import process_webhook_event
        process_webhook_event.delay(webhook_event.id)

        log_webhook(f"  ✓ Async task triggered")

        # === STEP 11: Return 200 OK immediately ===
        # eBay expects a quick response (< 3 seconds)
        return jsonify({
            'status': 'received',
            'event_id': event_id,
            'message': 'Event received and queued for processing'
        }), 200

    except Exception as e:
        log_webhook(f"✗ Error processing webhook: {str(e)}")

        # Try to log error to database if possible
        try:
            error_event = WebhookEvent(
                user_id=None,
                event_id=f"error_{datetime.utcnow().timestamp()}",
                topic='ERROR',
                payload={'error': str(e), 'raw_payload': request.get_data().decode('utf-8', errors='ignore')},
                status='failed',
                error_message=str(e)
            )
            db.session.add(error_event)
            db.session.commit()
        except:
            pass  # If we can't log to DB, just log to console

        # Still return 200 to prevent eBay from retrying immediately
        return jsonify({'status': 'error', 'message': 'Internal error'}), 200


def get_user_id_from_event(event_data: dict) -> int:
    """
    Determine user_id from event data

    This is a placeholder implementation.
    In production, you'd need to:
    1. Extract seller ID or other identifier from event
    2. Look up user in your database by eBay user ID
    3. Return the Qventory user_id

    Args:
        event_data: Parsed event data

    Returns:
        int: User ID or None
    """
    # TODO: Implement actual user mapping logic
    # For now, return None to flag for manual review
    return None


def get_event_priority(topic: str) -> int:
    """
    Determine processing priority based on event topic

    Priority levels:
    1 = Highest (process immediately)
    5 = Normal
    10 = Lowest (can be delayed)

    Args:
        topic: Event topic/type

    Returns:
        int: Priority level (1-10)
    """
    high_priority_topics = [
        'ITEM_SOLD',
        'ITEM_OUT_OF_STOCK'
    ]

    medium_priority_topics = [
        'FULFILLMENT_ORDER_SHIPPED',
        'FULFILLMENT_ORDER_DELIVERED'
    ]

    if topic in high_priority_topics:
        return 1
    elif topic in medium_priority_topics:
        return 3
    else:
        return 5


# === Health check endpoint ===
@webhook_bp.route('/health', methods=['GET'])
def webhook_health():
    """
    Health check endpoint for monitoring
    """
    return jsonify({
        'status': 'healthy',
        'service': 'webhooks',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


# === Subscription Management Endpoints ===

@webhook_bp.route('/subscriptions', methods=['GET'])
def list_subscriptions():
    """
    List all webhook subscriptions for current user
    Requires authentication
    """
    from flask_login import login_required, current_user
    from qventory.models.webhook import WebhookSubscription

    # Check if user is authenticated
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    # Get subscriptions from database
    subscriptions = WebhookSubscription.query.filter_by(
        user_id=current_user.id
    ).order_by(WebhookSubscription.created_at.desc()).all()

    return jsonify({
        'subscriptions': [sub.to_dict() for sub in subscriptions],
        'total': len(subscriptions)
    }), 200


@webhook_bp.route('/subscriptions/create', methods=['POST'])
def create_subscription():
    """
    Create a new webhook subscription
    Requires authentication
    """
    from flask_login import login_required, current_user
    from qventory.models.webhook import WebhookSubscription
    from qventory.helpers.ebay_webhooks import create_webhook_subscription

    # Check if user is authenticated
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    # Get request data
    data = request.get_json()
    topic = data.get('topic')

    if not topic:
        return jsonify({'error': 'Topic is required'}), 400

    # Get webhook base URL from environment
    webhook_base_url = os.environ.get('WEBHOOK_BASE_URL')
    if not webhook_base_url:
        return jsonify({'error': 'WEBHOOK_BASE_URL not configured'}), 500

    delivery_url = f"{webhook_base_url}/webhooks/ebay"

    log_webhook(f"Creating subscription for user {current_user.id}, topic: {topic}")

    # Check if subscription already exists
    existing = WebhookSubscription.query.filter_by(
        user_id=current_user.id,
        topic=topic,
        status='ENABLED'
    ).first()

    if existing:
        return jsonify({
            'error': 'Subscription already exists',
            'subscription': existing.to_dict()
        }), 409

    # Create subscription with eBay
    result = create_webhook_subscription(current_user.id, topic, delivery_url)

    if not result['success']:
        log_webhook(f"✗ Failed to create subscription: {result.get('error')}")
        return jsonify({'error': result.get('error')}), 500

    # Save to database
    subscription = WebhookSubscription(
        user_id=current_user.id,
        subscription_id=result['subscription_id'],
        topic=topic,
        status='ENABLED',
        delivery_url=delivery_url,
        expires_at=result['expires_at']
    )

    db.session.add(subscription)
    db.session.commit()

    log_webhook(f"✓ Subscription created and saved: {subscription.id}")

    return jsonify({
        'success': True,
        'subscription': subscription.to_dict()
    }), 201


@webhook_bp.route('/subscriptions/<int:subscription_id>/renew', methods=['POST'])
def renew_subscription(subscription_id):
    """
    Manually renew a webhook subscription
    Requires authentication
    """
    from flask_login import login_required, current_user
    from qventory.models.webhook import WebhookSubscription
    from qventory.helpers.ebay_webhooks import renew_webhook_subscription

    # Check if user is authenticated
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    # Get subscription
    subscription = WebhookSubscription.query.get(subscription_id)

    if not subscription:
        return jsonify({'error': 'Subscription not found'}), 404

    if subscription.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    log_webhook(f"Manually renewing subscription {subscription_id}")

    # Renew with eBay
    result = renew_webhook_subscription(current_user.id, subscription.subscription_id)

    if not result['success']:
        log_webhook(f"✗ Renewal failed: {result.get('error')}")
        subscription.mark_error(result.get('error'))
        return jsonify({'error': result.get('error')}), 500

    # Update database
    subscription.expires_at = result['expires_at']
    subscription.last_renewed_at = datetime.utcnow()
    subscription.renewal_attempts = 0
    subscription.status = 'ENABLED'
    db.session.commit()

    log_webhook(f"✓ Subscription renewed: {subscription_id}")

    return jsonify({
        'success': True,
        'subscription': subscription.to_dict()
    }), 200


@webhook_bp.route('/subscriptions/<int:subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    """
    Delete a webhook subscription
    Requires authentication
    """
    from flask_login import login_required, current_user
    from qventory.models.webhook import WebhookSubscription
    from qventory.helpers.ebay_webhooks import delete_webhook_subscription

    # Check if user is authenticated
    if not current_user.is_authenticated:
        return jsonify({'error': 'Authentication required'}), 401

    # Get subscription
    subscription = WebhookSubscription.query.get(subscription_id)

    if not subscription:
        return jsonify({'error': 'Subscription not found'}), 404

    if subscription.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    log_webhook(f"Deleting subscription {subscription_id}")

    # Delete from eBay
    result = delete_webhook_subscription(
        current_user.id,
        subscription.subscription_id
    )

    if not result['success']:
        log_webhook(f"⚠️  eBay deletion failed: {result.get('error')}, removing from DB anyway")

    # Delete from database
    db.session.delete(subscription)
    db.session.commit()

    log_webhook(f"✓ Subscription deleted: {subscription_id}")

    return jsonify({'success': True}), 200


@webhook_bp.route('/topics', methods=['GET'])
def list_available_topics():
    """
    List all available webhook topics
    """
    from qventory.helpers.ebay_webhooks import AVAILABLE_TOPICS, get_recommended_topics

    recommended = get_recommended_topics()

    topics = []
    for topic_id, info in AVAILABLE_TOPICS.items():
        topics.append({
            'id': topic_id,
            'category': info['category'],
            'description': info['description'],
            'priority': info['priority'],
            'recommended': topic_id in recommended
        })

    return jsonify({
        'topics': topics,
        'total': len(topics)
    }), 200
