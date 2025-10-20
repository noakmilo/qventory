#!/usr/bin/env python3
"""
Test script for webhook auto-renewal system
Tests the renewal task manually without waiting for Celery Beat
"""
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

def test_renewal_task():
    """Test the renewal task directly"""
    from qventory import create_app
    from qventory.tasks import renew_expiring_webhooks
    from qventory.models.webhook import WebhookSubscription
    from qventory.extensions import db
    from datetime import datetime, timedelta

    print("=" * 80)
    print("WEBHOOK AUTO-RENEWAL TEST")
    print("=" * 80)

    app = create_app()

    with app.app_context():
        # Check current subscriptions
        all_subs = WebhookSubscription.query.all()
        print(f"\n📊 Total subscriptions in database: {len(all_subs)}")

        if not all_subs:
            print("❌ No subscriptions found. Create some first by connecting eBay.")
            return

        # Show all subscriptions
        print("\n📋 Current subscriptions:")
        for sub in all_subs:
            days_until_expiry = (sub.expires_at - datetime.utcnow()).days
            print(f"\n  ID: {sub.id}")
            print(f"  User: {sub.user_id}")
            print(f"  Topic: {sub.topic}")
            print(f"  Status: {sub.status}")
            print(f"  Expires: {sub.expires_at} ({days_until_expiry} days)")
            print(f"  Needs renewal: {'YES' if sub.needs_renewal() else 'NO'}")
            print(f"  Is expired: {'YES' if sub.is_expired() else 'NO'}")
            print(f"  Error count: {sub.error_count or 0}")

        # Check which ones need renewal
        threshold = datetime.utcnow() + timedelta(days=2)
        expiring_subs = WebhookSubscription.query.filter(
            WebhookSubscription.status == 'ENABLED',
            WebhookSubscription.expires_at <= threshold
        ).all()

        print(f"\n⏰ Subscriptions expiring within 2 days: {len(expiring_subs)}")

        if not expiring_subs:
            print("\n✅ No subscriptions need renewal right now.")
            print("\n💡 To test the renewal system:")
            print("   1. Wait until subscriptions are closer to expiration (within 2 days)")
            print("   2. Or manually update a subscription's expires_at to trigger renewal")
            print("\n   Example SQL to trigger renewal test:")
            print("   UPDATE webhook_subscriptions SET expires_at = NOW() + INTERVAL '1 day' WHERE id = 1;")
            return

        # Run the renewal task
        print("\n🔄 Running auto-renewal task...")
        print("-" * 80)

        result = renew_expiring_webhooks.run()

        print("-" * 80)
        print("\n📊 Renewal Results:")
        print(f"   Total checked: {result['total_checked']}")
        print(f"   ✅ Renewed: {result['renewed']}")
        print(f"   ❌ Failed: {result['failed']}")

        if result['renewed'] > 0:
            print("\n✅ SUCCESS! Subscriptions were renewed.")

            # Show updated subscriptions
            print("\n📋 Updated subscriptions:")
            for sub in expiring_subs:
                db.session.refresh(sub)
                days_until_expiry = (sub.expires_at - datetime.utcnow()).days
                print(f"\n  ID: {sub.id} - {sub.topic}")
                print(f"  New expiration: {sub.expires_at} ({days_until_expiry} days)")

        if result['failed'] > 0:
            print("\n⚠️  Some renewals failed. Check the logs above for details.")
            print("   Common causes:")
            print("   - eBay access token expired (user needs to reconnect)")
            print("   - Invalid subscription ID")
            print("   - Network/API errors")


def test_celery_beat_schedule():
    """Test that Celery Beat schedule is configured correctly"""
    from qventory.celery_app import celery

    print("\n" + "=" * 80)
    print("CELERY BEAT SCHEDULE CHECK")
    print("=" * 80)

    schedule = celery.conf.beat_schedule

    if 'renew-webhooks-daily' in schedule:
        task_config = schedule['renew-webhooks-daily']
        print("\n✅ Renewal task is configured in Celery Beat")
        print(f"\n   Task: {task_config['task']}")
        print(f"   Schedule: Daily at 2:00 AM UTC")
        print(f"   Expires: {task_config['options']['expires']} seconds")
    else:
        print("\n❌ ERROR: Renewal task not found in Celery Beat schedule!")
        return False

    return True


def show_instructions():
    """Show instructions for running Celery Beat"""
    print("\n" + "=" * 80)
    print("HOW TO RUN CELERY BEAT (FOR SCHEDULED TASKS)")
    print("=" * 80)

    print("""
In production, you need to run THREE processes:

1. Flask app (Gunicorn):
   gunicorn -w 4 -b 0.0.0.0:5000 run:app

2. Celery worker (processes tasks):
   celery -A qventory.celery_app worker --loglevel=info

3. Celery Beat (scheduler):
   celery -A qventory.celery_app beat --loglevel=info

The Celery Beat scheduler will automatically trigger the renewal task
every day at 2:00 AM UTC.

For testing the schedule locally:
   celery -A qventory.celery_app beat --loglevel=debug
""")


if __name__ == '__main__':
    try:
        # Test the renewal task
        test_renewal_task()

        # Check Celery Beat configuration
        test_celery_beat_schedule()

        # Show instructions
        show_instructions()

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
