"""
Fulfillment sync helpers shared by routes and scheduled jobs.
"""
import sys
from datetime import datetime

from qventory.extensions import db
from qventory.helpers.ebay_inventory import fetch_ebay_orders, parse_ebay_order_to_sale
from qventory.helpers.tracking import detect_carrier
from qventory.models.sale import Sale
from qventory.models.item import Item


def log_fulfillment(msg):
    """Helper for fulfillment sync logs."""
    print(f"[FULFILLMENT_SYNC] {msg}", file=sys.stderr, flush=True)


def sync_fulfillment_orders(user_id, *, limit=800, filter_status='FULFILLED,IN_PROGRESS,NOT_STARTED'):
    """
    Sync fulfillment orders for a single user and update delivered status.
    """
    result = fetch_ebay_orders(user_id, filter_status=filter_status, limit=limit)
    if not result.get('success'):
        return {
            'success': False,
            'error': result.get('error', 'Failed to fetch orders'),
            'orders_synced': 0,
            'orders_created': 0,
            'orders_updated': 0
        }

    orders = result.get('orders') or []
    if not orders:
        return {
            'success': True,
            'message': 'No new orders to sync',
            'orders_synced': 0,
            'orders_created': 0,
            'orders_updated': 0
        }

    orders_created = 0
    orders_updated = 0

    for order_data in orders:
        try:
            sale_data = parse_ebay_order_to_sale(order_data, user_id=user_id)
            if not sale_data:
                log_fulfillment(f"Failed to parse order {order_data.get('orderId', 'UNKNOWN')}")
                continue

            existing_sale = Sale.query.filter_by(
                user_id=user_id,
                marketplace_order_id=sale_data['marketplace_order_id']
            ).first()

            tracking_number = sale_data.get('tracking_number')
            carrier_hint = sale_data.get('carrier')
            if not carrier_hint and tracking_number:
                carrier_hint = detect_carrier(tracking_number)
                if carrier_hint != 'Unknown':
                    sale_data['carrier'] = carrier_hint

            if existing_sale:
                existing_sale.tracking_number = sale_data.get('tracking_number') or existing_sale.tracking_number
                existing_sale.carrier = sale_data.get('carrier') or existing_sale.carrier
                existing_sale.shipped_at = sale_data.get('shipped_at') or existing_sale.shipped_at
                existing_sale.status = sale_data.get('status') or existing_sale.status

                delivered_value = sale_data.get('delivered_at')
                if delivered_value:
                    existing_sale.delivered_at = delivered_value
                    existing_sale.status = 'delivered'

                existing_sale.updated_at = datetime.utcnow()
                db.session.commit()
                orders_updated += 1
            else:
                item_id = None
                if sale_data.get('item_sku'):
                    item = Item.query.filter_by(
                        user_id=user_id,
                        sku=sale_data['item_sku']
                    ).first()
                    if item:
                        item_id = item.id
                        if item.item_cost:
                            sale_data['item_cost'] = item.item_cost

                sale_payload = sale_data.copy()
                sale_payload.pop('ebay_listing_id', None)
                new_sale = Sale(
                    user_id=user_id,
                    item_id=item_id,
                    **sale_payload
                )
                new_sale.calculate_profit()
                db.session.add(new_sale)
                db.session.commit()
                orders_created += 1
        except Exception as exc:
            log_fulfillment(f"Error processing order: {exc}")
            db.session.rollback()
            continue

    return {
        'success': True,
        'orders_synced': orders_created + orders_updated,
        'orders_created': orders_created,
        'orders_updated': orders_updated
    }
