"""
Webhook Auto-Setup Helper
Automatically creates webhook subscriptions when user connects eBay
"""
import os
import sys
from datetime import datetime
from qventory.extensions import db
from qventory.models.webhook import WebhookSubscription
from qventory.helpers.ebay_webhooks import create_webhook_subscription, get_recommended_topics


def log_auto_setup(msg):
    """Helper for auto-setup logging"""
    print(f"[WEBHOOK_AUTO_SETUP] {msg}", file=sys.stderr, flush=True)


def auto_setup_webhooks(user_id: int) -> dict:
    """
    Automatically setup webhook subscriptions for a user

    Called after user successfully connects their eBay account.
    Creates subscriptions for recommended topics automatically.

    Args:
        user_id: Qventory user ID

    Returns:
        dict: {
            'success': bool,
            'created': int (number of subscriptions created),
            'failed': int (number that failed),
            'skipped': int (number already existing),
            'details': list of results
        }
    """
    log_auto_setup(f"Auto-setup webhooks for user {user_id}")

    # Get webhook base URL
    webhook_base_url = os.environ.get('WEBHOOK_BASE_URL')
    if not webhook_base_url:
        log_auto_setup("✗ WEBHOOK_BASE_URL not configured - skipping auto-setup")
        return {
            'success': False,
            'error': 'WEBHOOK_BASE_URL not configured',
            'created': 0,
            'failed': 0,
            'skipped': 0
        }

    delivery_url = f"{webhook_base_url}/webhooks/ebay"

    # Get recommended topics
    topics = get_recommended_topics()
    log_auto_setup(f"Setting up {len(topics)} recommended topics")

    created_count = 0
    failed_count = 0
    skipped_count = 0
    details = []

    for topic in topics:
        try:
            # Check if subscription already exists
            existing = WebhookSubscription.query.filter_by(
                user_id=user_id,
                topic=topic,
                status='ENABLED'
            ).first()

            if existing:
                log_auto_setup(f"  ⊘ {topic}: Already exists (subscription {existing.id})")
                skipped_count += 1
                details.append({
                    'topic': topic,
                    'status': 'skipped',
                    'reason': 'Already exists'
                })
                continue

            log_auto_setup(f"  → Creating subscription for: {topic}")

            # Create subscription with eBay
            result = create_webhook_subscription(user_id, topic, delivery_url)

            if not result['success']:
                log_auto_setup(f"  ✗ {topic}: Failed - {result.get('error')}")
                failed_count += 1
                details.append({
                    'topic': topic,
                    'status': 'failed',
                    'error': result.get('error')
                })
                continue

            # Save to database
            subscription = WebhookSubscription(
                user_id=user_id,
                subscription_id=result['subscription_id'],
                topic=topic,
                status='ENABLED',
                delivery_url=delivery_url,
                expires_at=result['expires_at']
            )

            db.session.add(subscription)
            db.session.commit()

            log_auto_setup(f"  ✓ {topic}: Created (subscription {subscription.id})")
            created_count += 1
            details.append({
                'topic': topic,
                'status': 'created',
                'subscription_id': subscription.id
            })

        except Exception as e:
            log_auto_setup(f"  ✗ {topic}: Exception - {str(e)}")
            failed_count += 1
            details.append({
                'topic': topic,
                'status': 'error',
                'error': str(e)
            })
            # Continue with next topic even if one fails
            continue

    log_auto_setup(f"Auto-setup complete: {created_count} created, {failed_count} failed, {skipped_count} skipped")

    return {
        'success': True,
        'created': created_count,
        'failed': failed_count,
        'skipped': skipped_count,
        'details': details
    }


def cleanup_expired_subscriptions(user_id: int = None) -> dict:
    """
    Clean up expired webhook subscriptions

    Called periodically by Celery task to remove expired subscriptions
    that were not renewed.

    Args:
        user_id: Optional - clean up for specific user, or None for all users

    Returns:
        dict: {
            'deleted': int (number of subscriptions deleted),
            'details': list of deleted subscription IDs
        }
    """
    from datetime import datetime

    log_auto_setup(f"Cleaning up expired subscriptions{f' for user {user_id}' if user_id else ''}")

    # Find expired subscriptions
    query = WebhookSubscription.query.filter(
        WebhookSubscription.expires_at < datetime.utcnow()
    )

    if user_id:
        query = query.filter_by(user_id=user_id)

    expired_subs = query.all()

    deleted_count = 0
    deleted_ids = []

    for sub in expired_subs:
        log_auto_setup(f"  Deleting expired subscription {sub.id} (topic: {sub.topic}, expired: {sub.expires_at})")
        deleted_ids.append(sub.id)
        db.session.delete(sub)
        deleted_count += 1

    db.session.commit()

    log_auto_setup(f"Cleanup complete: {deleted_count} expired subscriptions deleted")

    return {
        'deleted': deleted_count,
        'details': deleted_ids
    }
