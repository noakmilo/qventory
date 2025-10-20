#!/usr/bin/env python3
"""
Test script for eBay webhook endpoint
Simulates an eBay webhook event with proper signature
"""
import os
import sys
import json
import hmac
import hashlib
import base64
import requests
from datetime import datetime

def create_test_payload():
    """Create a test eBay webhook payload"""
    return {
        "metadata": {
            "topic": "ITEM_SOLD",
            "eventId": f"test-event-{datetime.utcnow().timestamp()}",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        },
        "notification": {
            "itemId": "123456789",
            "sku": "TEST-SKU-001",
            "title": "Test Item - Laptop",
            "soldPrice": 500.00,
            "quantity": 1,
            "buyerId": "test_buyer_123"
        }
    }

def sign_payload(payload_bytes, client_secret):
    """Create HMAC-SHA256 signature like eBay does"""
    signature = hmac.new(
        client_secret.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

def test_challenge_response(webhook_url):
    """Test eBay challenge code verification"""
    print("\n=== Testing Challenge Response ===")
    challenge_code = "test-challenge-12345"

    response = requests.get(
        webhook_url,
        params={'challenge_code': challenge_code}
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

    if response.status_code == 200:
        data = response.json()
        if data.get('challengeResponse') == challenge_code:
            print("✅ Challenge response test PASSED")
            return True
        else:
            print("❌ Challenge response mismatch")
            return False
    else:
        print("❌ Challenge response test FAILED")
        return False

def test_webhook_event(webhook_url, client_secret):
    """Test webhook event processing"""
    print("\n=== Testing Webhook Event ===")

    # Create payload
    payload = create_test_payload()
    payload_json = json.dumps(payload)
    payload_bytes = payload_json.encode('utf-8')

    # Sign payload
    signature = sign_payload(payload_bytes, client_secret)

    print(f"Event ID: {payload['metadata']['eventId']}")
    print(f"Topic: {payload['metadata']['topic']}")
    print(f"Signature: {signature[:30]}...")

    # Send request
    headers = {
        'Content-Type': 'application/json',
        'X-EBAY-SIGNATURE': signature
    }

    response = requests.post(
        webhook_url,
        data=payload_bytes,
        headers=headers
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

    if response.status_code == 200:
        data = response.json()
        if data.get('status') == 'received':
            print("✅ Webhook event test PASSED")
            return True
        else:
            print("⚠️  Unexpected response status")
            return False
    else:
        print("❌ Webhook event test FAILED")
        return False

def main():
    # Get configuration from environment or command line
    if len(sys.argv) > 1:
        webhook_url = sys.argv[1]
    else:
        webhook_url = os.environ.get('WEBHOOK_URL', 'http://localhost:5000/webhooks/ebay')

    if len(sys.argv) > 2:
        client_secret = sys.argv[2]
    else:
        client_secret = os.environ.get('EBAY_CLIENT_SECRET')

    if not client_secret:
        print("❌ ERROR: EBAY_CLIENT_SECRET not provided")
        print("\nUsage:")
        print("  python test_webhook.py <webhook_url> <client_secret>")
        print("  OR set WEBHOOK_URL and EBAY_CLIENT_SECRET environment variables")
        sys.exit(1)

    print(f"Testing webhook at: {webhook_url}")
    print(f"Using client secret: {client_secret[:10]}...")

    # Run tests
    challenge_ok = test_challenge_response(webhook_url)
    event_ok = test_webhook_event(webhook_url, client_secret)

    print("\n" + "="*50)
    if challenge_ok and event_ok:
        print("✅ ALL TESTS PASSED")
        print("\nNext steps:")
        print("1. Check database for the test event:")
        print("   SELECT * FROM webhook_events ORDER BY id DESC LIMIT 1;")
        print("2. Check Celery logs for processing:")
        print("   sudo journalctl -u celery-qventory -n 50")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)

if __name__ == '__main__':
    main()
