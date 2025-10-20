"""
eBay Platform Notifications (SOAP) Webhook Routes
Handles incoming Platform Notifications from eBay Trading API

Platform Notifications provide real-time updates for:
- AddItem (new listing created)
- ReviseItem (listing updated)
- RelistItem (listing relisted)
- EndItem (listing ended)

These are SOAP/XML based notifications (different from Commerce API's JSON)
"""
import os
import json
import xml.etree.ElementTree as ET
from flask import Blueprint, request, jsonify
from datetime import datetime
from qventory.extensions import db
from qventory.models.webhook import WebhookEvent, WebhookProcessingQueue
from qventory.helpers.webhook_helpers import log_webhook

platform_webhook_bp = Blueprint('platform_webhooks', __name__, url_prefix='/webhooks')

# eBay Platform Notifications namespace
EBAY_NS = {
    'soapenv': 'http://schemas.xmlsoap.org/soap/envelope/',
    'ebl': 'urn:ebay:apis:eBLBaseComponents'
}


@platform_webhook_bp.route('/ebay-platform', methods=['POST'])
def ebay_platform_webhook():
    """
    Platform Notifications webhook endpoint

    Receives SOAP/XML notifications from eBay Trading API for:
    - AddItem: New listing created
    - ReviseItem: Listing details updated
    - RelistItem: Listing relisted after ending
    - EndItem: Listing ended

    Unlike Commerce API (JSON), these are XML/SOAP format.
    """
    try:
        # === STEP 1: Get raw XML payload ===
        raw_payload = request.get_data()
        content_type = request.headers.get('Content-Type', '')

        log_webhook(f"[PLATFORM] Received Platform Notification")
        log_webhook(f"  Content-Type: {content_type}")
        log_webhook(f"  Payload size: {len(raw_payload)} bytes")

        # === STEP 2: Parse SOAP/XML ===
        try:
            root = ET.fromstring(raw_payload)
        except ET.ParseError as e:
            log_webhook(f"✗ Invalid XML: {str(e)}")
            return jsonify({'error': 'Invalid XML'}), 400

        # === STEP 3: Extract notification data ===
        event_data = parse_platform_notification(root)

        if not event_data:
            log_webhook("✗ Could not parse notification data")
            return jsonify({'error': 'Invalid notification structure'}), 400

        notification_type = event_data.get('notification_type')
        item_id = event_data.get('item_id')

        log_webhook(f"  Notification Type: {notification_type}")
        log_webhook(f"  Item ID: {item_id}")

        # === STEP 4: Generate unique event ID ===
        event_id = f"platform_{notification_type}_{item_id}_{datetime.utcnow().timestamp()}"

        # === STEP 5: Check for duplicates (basic dedup) ===
        existing = WebhookEvent.query.filter_by(event_id=event_id).first()
        if existing:
            log_webhook(f"  ⊘ Duplicate event - already processed")
            return jsonify({'status': 'duplicate'}), 200

        # === STEP 6: Determine user_id from eBay seller ID ===
        seller_id = event_data.get('seller_id')
        user_id = get_user_id_from_seller_id(seller_id) if seller_id else None

        if not user_id:
            log_webhook(f"⚠️  Could not map seller_id '{seller_id}' to user_id")

        # === STEP 7: Store event in database ===
        webhook_event = WebhookEvent(
            user_id=user_id,
            event_id=event_id,
            topic=f'PLATFORM_{notification_type}',
            payload={
                'notification_type': notification_type,
                'item_id': item_id,
                'seller_id': seller_id,
                'data': event_data.get('data', {}),
                'raw_xml': raw_payload.decode('utf-8', errors='ignore')
            },
            headers={'content-type': content_type},
            ebay_timestamp=event_data.get('timestamp'),
            status='pending'
        )

        db.session.add(webhook_event)
        db.session.commit()

        log_webhook(f"  ✓ Event stored with ID: {webhook_event.id}")

        # === STEP 8: Queue for processing ===
        priority = get_platform_event_priority(notification_type)

        queue_item = WebhookProcessingQueue(
            event_id=webhook_event.id,
            priority=priority,
            status='queued'
        )

        db.session.add(queue_item)
        db.session.commit()

        log_webhook(f"  ✓ Queued for processing (priority: {priority})")

        # === STEP 9: Trigger async processing ===
        from qventory.tasks import process_platform_notification
        process_platform_notification.delay(webhook_event.id)

        log_webhook(f"  ✓ Async task triggered")

        # === STEP 10: Return 200 OK ===
        return jsonify({
            'status': 'received',
            'event_id': event_id,
            'message': 'Platform notification received'
        }), 200

    except Exception as e:
        log_webhook(f"✗ Error processing Platform Notification: {str(e)}")

        # Try to log error
        try:
            error_event = WebhookEvent(
                user_id=None,
                event_id=f"platform_error_{datetime.utcnow().timestamp()}",
                topic='PLATFORM_ERROR',
                payload={'error': str(e), 'raw': raw_payload.decode('utf-8', errors='ignore')[:1000]},
                status='failed',
                error_message=str(e)
            )
            db.session.add(error_event)
            db.session.commit()
        except:
            pass

        return jsonify({'status': 'error', 'message': 'Internal error'}), 200


def parse_platform_notification(root: ET.Element) -> dict:
    """
    Parse eBay Platform Notification SOAP/XML

    Example AddItem notification structure:
    <soapenv:Envelope>
      <soapenv:Body>
        <GetItemResponse>
          <Item>
            <ItemID>123456789012</ItemID>
            <Title>My Item</Title>
            <Seller>
              <UserID>seller_username</UserID>
            </Seller>
            ...
          </Item>
        </GetItemResponse>
      </soapenv:Body>
    </soapenv:Envelope>

    Args:
        root: XML root element

    Returns:
        dict: Parsed event data or None if invalid
    """
    try:
        # Find SOAP Body
        body = root.find('.//soapenv:Body', EBAY_NS)
        if body is None:
            body = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')

        if body is None:
            log_webhook("✗ Could not find SOAP Body")
            return None

        # Determine notification type by looking at response element
        notification_type = None
        response_elem = None

        for child in body:
            tag_name = child.tag.split('}')[-1]  # Remove namespace

            if 'GetItem' in tag_name:
                notification_type = 'AddItem'
                response_elem = child
                break
            elif 'ReviseItem' in tag_name:
                notification_type = 'ReviseItem'
                response_elem = child
                break
            elif 'RelistItem' in tag_name:
                notification_type = 'RelistItem'
                response_elem = child
                break
            elif 'EndItem' in tag_name:
                notification_type = 'EndItem'
                response_elem = child
                break

        if not notification_type:
            log_webhook("✗ Unknown notification type")
            return None

        # Extract Item element
        item_elem = response_elem.find('.//ebl:Item', EBAY_NS)
        if item_elem is None:
            item_elem = response_elem.find('.//{urn:ebay:apis:eBLBaseComponents}Item')

        if item_elem is None:
            log_webhook("✗ Could not find Item element")
            return None

        # Extract key fields
        item_id = get_xml_text(item_elem, './/ebl:ItemID', EBAY_NS)
        title = get_xml_text(item_elem, './/ebl:Title', EBAY_NS)
        seller_id = get_xml_text(item_elem, './/ebl:Seller/ebl:UserID', EBAY_NS)
        listing_type = get_xml_text(item_elem, './/ebl:ListingType', EBAY_NS)

        # Extract pricing
        start_price = get_xml_text(item_elem, './/ebl:StartPrice', EBAY_NS)
        buy_it_now_price = get_xml_text(item_elem, './/ebl:BuyItNowPrice', EBAY_NS)

        # Extract SKU if available
        sku = get_xml_text(item_elem, './/ebl:SKU', EBAY_NS)

        # Extract category
        primary_category = get_xml_text(item_elem, './/ebl:PrimaryCategory/ebl:CategoryID', EBAY_NS)

        # Extract quantity
        quantity = get_xml_text(item_elem, './/ebl:Quantity', EBAY_NS)

        # Extract listing URL
        view_url = get_xml_text(item_elem, './/ebl:ListingDetails/ebl:ViewItemURL', EBAY_NS)

        return {
            'notification_type': notification_type,
            'item_id': item_id,
            'seller_id': seller_id,
            'timestamp': datetime.utcnow(),
            'data': {
                'title': title,
                'listing_type': listing_type,
                'start_price': start_price,
                'buy_it_now_price': buy_it_now_price,
                'sku': sku,
                'primary_category': primary_category,
                'quantity': quantity,
                'view_url': view_url
            }
        }

    except Exception as e:
        log_webhook(f"✗ Error parsing Platform Notification XML: {str(e)}")
        return None


def get_xml_text(element: ET.Element, xpath: str, namespaces: dict) -> str:
    """
    Safely extract text from XML element

    Args:
        element: Parent XML element
        xpath: XPath expression
        namespaces: XML namespaces

    Returns:
        str: Element text or empty string
    """
    try:
        elem = element.find(xpath, namespaces)
        if elem is None:
            # Try without namespace
            xpath_no_ns = xpath.replace('ebl:', '')
            elem = element.find(xpath_no_ns)

        return elem.text if elem is not None and elem.text else ''
    except:
        return ''


def get_user_id_from_seller_id(seller_id: str) -> int:
    """
    Map eBay seller ID to Qventory user_id

    Args:
        seller_id: eBay seller username/ID

    Returns:
        int: Qventory user_id or None
    """
    try:
        from qventory.models.user import User

        # Look up user by eBay seller ID stored in oauth_data
        users = User.query.all()

        for user in users:
            if user.ebay_oauth_data:
                # Check if this user's eBay account matches
                oauth_data = user.ebay_oauth_data

                # The seller ID might be stored in different places
                stored_seller_id = oauth_data.get('ebay_user_id') or oauth_data.get('seller_id')

                if stored_seller_id and stored_seller_id.lower() == seller_id.lower():
                    log_webhook(f"  ✓ Mapped seller '{seller_id}' to user_id {user.id}")
                    return user.id

        return None

    except Exception as e:
        log_webhook(f"✗ Error mapping seller_id to user_id: {str(e)}")
        return None


def get_platform_event_priority(notification_type: str) -> int:
    """
    Determine processing priority for Platform Notifications

    Args:
        notification_type: Type of notification (AddItem, ReviseItem, etc.)

    Returns:
        int: Priority level (1-10, lower is higher priority)
    """
    # AddItem is highest priority - user expects real-time sync
    if notification_type == 'AddItem':
        return 1

    # ReviseItem is also high priority
    elif notification_type == 'ReviseItem':
        return 2

    # Other notifications are lower priority
    else:
        return 5


@platform_webhook_bp.route('/platform/health', methods=['GET'])
def platform_health():
    """Health check for Platform Notifications endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'platform_webhooks',
        'timestamp': datetime.utcnow().isoformat()
    }), 200
