"""Report confirmed stale inventory; pass --apply explicitly to deactivate it.

Run with the same environment and Python environment as the web application:
    python reconcile_inventory.py --user-id 22 --user-id 51
    python reconcile_inventory.py --user-id 22 --apply

Only inventory state changes. Sales, costs and the original items are preserved.
"""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, action='append', required=True)
    parser.add_argument('--apply', action='store_true', help='Deactivate confirmed stale items')
    args = parser.parse_args()

    from qventory import create_app
    from qventory.extensions import db
    from qventory.models.item import Item
    from qventory.helpers.ebay_inventory import fetch_active_listings_snapshot
    from qventory.helpers.inventory_reconciliation import confirmed_inactive_listing_ids
    from qventory.helpers.link_bio import remove_featured_items_for_user

    from datetime import datetime

    with create_app().app_context():
        for user_id in sorted(set(args.user_id)):
            try:
                items = Item.query.filter(
                    Item.user_id == user_id, Item.is_active.is_(True),
                    Item.ebay_listing_id.isnot(None),
                ).all()
                snapshot = fetch_active_listings_snapshot(user_id)
                confirmed = confirmed_inactive_listing_ids(
                    user_id, snapshot, [item.ebay_listing_id for item in items],
                )
                candidates = [item for item in items if str(item.ebay_listing_id) in confirmed]
                print(json.dumps({
                    'user_id': user_id, 'mode': 'apply' if args.apply else 'report',
                    'snapshot_complete': bool(snapshot.get('can_mark_inactive')),
                    'error': snapshot.get('error'),
                    'confirmed_items': [{'id': item.id, 'ebay_listing_id': item.ebay_listing_id}
                                        for item in candidates],
                }), flush=True)
                if args.apply:
                    for item in candidates:
                        item.is_active = False
                        item.last_ebay_sync = datetime.utcnow()
                        item.notes = (item.notes or '') + '\nConfirmed inactive by inventory repair.'
                    remove_featured_items_for_user(user_id, [item.id for item in candidates])
                    db.session.commit()
                else:
                    db.session.rollback()
            except Exception:
                db.session.rollback()
                raise


if __name__ == '__main__':
    main()
