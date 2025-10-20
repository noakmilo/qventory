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


def setup_platform_notifications(user_id: int) -> dict:
    """
    Setup eBay Platform Notifications (Trading API SOAP webhooks)

    This enables real-time notifications for:
    - AddItem: New listing created
    - ReviseItem: Listing updated
    - RelistItem: Listing relisted

    Uses Trading API's SetNotificationPreferences call.

    Args:
        user_id: Qventory user ID

    Returns:
        dict: {
            'success': bool,
            'message': str,
            'topics_enabled': list of enabled topics
        }
    """
    log_auto_setup(f"Setting up Platform Notifications for user {user_id}")

    try:
        from qventory.models.user import User

        # Get user's eBay credentials
        user = User.query.get(user_id)
        if not user or not user.ebay_oauth_data:
            log_auto_setup("✗ User not found or no eBay OAuth data")
            return {
                'success': False,
                'error': 'No eBay credentials found'
            }

        # Get webhook base URL
        webhook_base_url = os.environ.get('WEBHOOK_BASE_URL')
        if not webhook_base_url:
            log_auto_setup("✗ WEBHOOK_BASE_URL not configured")
            return {
                'success': False,
                'error': 'WEBHOOK_BASE_URL not configured'
            }

        application_url = f"{webhook_base_url}/webhooks/ebay-platform"

        log_auto_setup(f"Application URL: {application_url}")

        # Call SetNotificationPreferences
        result = set_notification_preferences(
            application_url=application_url,
            user_id=user_id
        )

        if result['success']:
            log_auto_setup(f"✓ Platform Notifications enabled: {', '.join(result['topics_enabled'])}")
        else:
            log_auto_setup(f"✗ Failed to enable Platform Notifications: {result.get('error')}")

        return result

    except Exception as e:
        log_auto_setup(f"✗ Exception setting up Platform Notifications: {str(e)}")
        import traceback
        log_auto_setup(f"Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e)
        }


def set_notification_preferences(application_url: str, user_id: int) -> dict:
    """
    Call eBay Trading API SetNotificationPreferences

    This is a SOAP XML API call (different from REST APIs).

    Args:
        application_url: URL where eBay will send notifications
        user_id: User ID for logging

    Returns:
        dict: Success/failure result
    """
    import requests
    import xml.etree.ElementTree as ET

    log_auto_setup(f"Calling SetNotificationPreferences API")

    try:
        # Get Trading API credentials
        ebay_app_id = os.environ.get('EBAY_CLIENT_ID')
        ebay_dev_id = os.environ.get('EBAY_DEV_ID')
        ebay_cert_id = os.environ.get('EBAY_CERT_ID')

        # Get user's OAuth token from database
        from qventory.models.user import User
        user = User.query.get(user_id)
        ebay_user_token = None
        if user and user.ebay_oauth_data:
            ebay_user_token = user.ebay_oauth_data.get('access_token')

        if not all([ebay_app_id, ebay_dev_id, ebay_cert_id, ebay_user_token]):
            log_auto_setup("✗ Missing Trading API credentials")
            return {
                'success': False,
                'error': 'Missing Trading API credentials (need EBAY_DEV_ID, EBAY_CERT_ID)'
            }

        # Determine Trading API endpoint (sandbox vs production)
        is_sandbox = os.environ.get('EBAY_SANDBOX', 'false').lower() == 'true'
        trading_api_url = (
            'https://api.sandbox.ebay.com/ws/api.dll'
            if is_sandbox else
            'https://api.ebay.com/ws/api.dll'
        )

        # Build SOAP XML request for SetNotificationPreferences
        soap_body = f'''<?xml version="1.0" encoding="utf-8"?>
<SetNotificationPreferencesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{ebay_user_token}</eBayAuthToken>
  </RequesterCredentials>
  <ApplicationDeliveryPreferences>
    <ApplicationEnable>Enable</ApplicationEnable>
    <ApplicationURL>{application_url}</ApplicationURL>
    <DeviceType>Platform</DeviceType>
  </ApplicationDeliveryPreferences>
  <UserDeliveryPreferenceArray>
    <NotificationEnable>
      <EventType>ItemListed</EventType>
      <EventEnable>Enable</EventEnable>
    </NotificationEnable>
    <NotificationEnable>
      <EventType>ItemRevised</EventType>
      <EventEnable>Enable</EventEnable>
    </NotificationEnable>
    <NotificationEnable>
      <EventType>ItemClosed</EventType>
      <EventEnable>Enable</EventEnable>
    </NotificationEnable>
    <NotificationEnable>
      <EventType>ItemSold</EventType>
      <EventEnable>Enable</EventEnable>
    </NotificationEnable>
  </UserDeliveryPreferenceArray>
  <WarningLevel>High</WarningLevel>
</SetNotificationPreferencesRequest>'''

        # Set up headers
        headers = {
            'X-EBAY-API-COMPATIBILITY-LEVEL': '1193',
            'X-EBAY-API-DEV-NAME': ebay_dev_id,
            'X-EBAY-API-APP-NAME': ebay_app_id,
            'X-EBAY-API-CERT-NAME': ebay_cert_id,
            'X-EBAY-API-CALL-NAME': 'SetNotificationPreferences',
            'X-EBAY-API-SITEID': '0',  # 0 = US
            'Content-Type': 'text/xml'
        }

        log_auto_setup("Sending SOAP request to Trading API...")

        # Make API call
        response = requests.post(
            trading_api_url,
            data=soap_body,
            headers=headers,
            timeout=30
        )

        log_auto_setup(f"Response status: {response.status_code}")

        if response.status_code != 200:
            log_auto_setup(f"✗ API returned status {response.status_code}")
            log_auto_setup(f"Response: {response.text[:500]}")
            return {
                'success': False,
                'error': f'Trading API returned status {response.status_code}'
            }

        # Parse XML response
        try:
            root = ET.fromstring(response.text)

            # Check for Ack=Success
            ack = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')

            if ack is not None and ack.text in ['Success', 'Warning']:
                log_auto_setup(f"✓ API call successful (Ack: {ack.text})")

                return {
                    'success': True,
                    'message': 'Platform Notifications enabled',
                    'topics_enabled': ['ItemListed', 'ItemRevised', 'ItemClosed', 'ItemSold']
                }
            else:
                # Extract error message
                errors = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
                error_msgs = []
                for error in errors:
                    long_msg = error.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage')
                    if long_msg is not None:
                        error_msgs.append(long_msg.text)

                error_text = '; '.join(error_msgs) if error_msgs else 'Unknown error'
                log_auto_setup(f"✗ API returned error: {error_text}")

                return {
                    'success': False,
                    'error': error_text
                }

        except ET.ParseError as e:
            log_auto_setup(f"✗ Failed to parse XML response: {str(e)}")
            log_auto_setup(f"Response: {response.text[:500]}")
            return {
                'success': False,
                'error': f'Failed to parse API response: {str(e)}'
            }

    except requests.exceptions.RequestException as e:
        log_auto_setup(f"✗ Network error calling Trading API: {str(e)}")
        return {
            'success': False,
            'error': f'Network error: {str(e)}'
        }
    except Exception as e:
        log_auto_setup(f"✗ Exception calling SetNotificationPreferences: {str(e)}")
        import traceback
        log_auto_setup(f"Traceback: {traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e)
        }
