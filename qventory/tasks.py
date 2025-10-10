"""
Celery Background Tasks for Qventory
"""
import sys
from datetime import datetime
from qventory.celery_app import celery
from qventory.extensions import db
from qventory import create_app

def log_task(msg):
    """Helper function for task logging"""
    print(f"[CELERY_TASK] {msg}", file=sys.stderr, flush=True)


@celery.task(bind=True, name='qventory.tasks.import_ebay_inventory')
def import_ebay_inventory(self, user_id, import_mode='new_only', listing_status='ACTIVE'):
    """
    Background task to import eBay inventory

    Args:
        user_id: Qventory user ID
        import_mode: 'new_only', 'update_existing', or 'sync_all'
        listing_status: 'ACTIVE' or 'ALL'

    Returns:
        dict with import results
    """
    # Create Flask app context (required for DB access)
    app = create_app()

    with app.app_context():
        from qventory.models.import_job import ImportJob
        from qventory.models.item import Item
        from qventory.helpers.ebay_inventory import get_all_inventory, parse_ebay_inventory_item
        from qventory.helpers import generate_sku

        log_task(f"=== Starting eBay import for user {user_id} ===")
        log_task(f"Mode: {import_mode}, Status: {listing_status}")
        log_task(f"Task ID: {self.request.id}")

        # Get or create ImportJob
        job = ImportJob.query.filter_by(celery_task_id=self.request.id).first()
        if not job:
            job = ImportJob(
                user_id=user_id,
                celery_task_id=self.request.id,
                import_mode=import_mode,
                listing_status=listing_status,
                status='processing',
                started_at=datetime.utcnow()
            )
            db.session.add(job)
            db.session.commit()

        try:
            # Update status
            job.status = 'processing'
            job.started_at = datetime.utcnow()
            db.session.commit()

            # Fetch inventory from eBay
            log_task("Fetching inventory from eBay API...")
            ebay_items = get_all_inventory(user_id, max_items=1000)
            log_task(f"Fetched {len(ebay_items)} items from eBay")

            job.total_items = len(ebay_items)
            db.session.commit()

            imported_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0

            for idx, ebay_item in enumerate(ebay_items):
                try:
                    log_task(f"Processing item {idx + 1}/{len(ebay_items)}")

                    # Parse eBay item (with image processing)
                    parsed = parse_ebay_inventory_item(ebay_item, process_images=True)
                    ebay_sku = parsed.get('ebay_sku', '')
                    ebay_title = parsed.get('title', '')

                    log_task(f"  Title: {ebay_title[:50]}")
                    log_task(f"  Image processed: {parsed.get('item_thumb', 'N/A')[:80]}")

                    # Check if location was detected from eBay SKU
                    if parsed.get('location_code'):
                        log_task(f"  Location detected: {parsed['location_code']}")

                    # Check if item already exists
                    existing_item = None
                    match_method = None
                    ebay_listing_id = parsed.get('ebay_listing_id')

                    log_task(f"  eBay Listing ID: {ebay_listing_id or 'None'}")
                    log_task(f"  eBay SKU: {ebay_sku or 'None'}")

                    # First try: Match by eBay Listing ID (most reliable)
                    if ebay_listing_id:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            ebay_listing_id=ebay_listing_id
                        ).first()
                        if existing_item:
                            match_method = "ebay_listing_id"

                    # Second try: Match by eBay SKU
                    if not existing_item and ebay_sku:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            ebay_sku=ebay_sku
                        ).first()
                        if existing_item:
                            match_method = "ebay_sku"

                    # Third try: Match by exact title (least reliable)
                    if not existing_item and ebay_title:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            title=ebay_title
                        ).first()
                        if existing_item:
                            match_method = "title"

                    if existing_item:
                        log_task(f"  ✓ Match found (method: {match_method}, Qventory ID: {existing_item.id}, mode: {import_mode})")

                        if import_mode in ['update_existing', 'sync_all']:
                            # Update eBay-specific fields
                            existing_item.synced_from_ebay = True
                            existing_item.last_ebay_sync = datetime.utcnow()

                            if parsed.get('ebay_listing_id'):
                                existing_item.ebay_listing_id = parsed['ebay_listing_id']
                            if parsed.get('ebay_url'):
                                existing_item.ebay_url = parsed['ebay_url']
                            if parsed.get('item_price'):
                                existing_item.item_price = parsed['item_price']
                            if parsed.get('item_thumb'):
                                existing_item.item_thumb = parsed['item_thumb']  # Update with Cloudinary URL
                            if ebay_sku and not existing_item.ebay_sku:
                                existing_item.ebay_sku = ebay_sku

                            updated_count += 1
                            log_task(f"  → Updated existing item")
                        else:
                            # new_only mode: skip items that already exist
                            skipped_count += 1
                            log_task(f"  → Skipped (already in Qventory)")
                    else:
                        log_task(f"  New item from eBay")

                        if import_mode in ['new_only', 'sync_all']:
                            new_sku = generate_sku()
                            new_item = Item(
                                user_id=user_id,
                                sku=new_sku,
                                title=ebay_title,
                                item_thumb=parsed.get('item_thumb'),  # Cloudinary URL
                                ebay_sku=ebay_sku,
                                ebay_listing_id=parsed.get('ebay_listing_id'),
                                ebay_url=parsed.get('ebay_url'),
                                item_price=parsed.get('item_price'),
                                # Import location from eBay Custom SKU if detected
                                A=parsed.get('location_A'),
                                B=parsed.get('location_B'),
                                S=parsed.get('location_S'),
                                C=parsed.get('location_C'),
                                location_code=parsed.get('location_code'),
                                synced_from_ebay=True,
                                last_ebay_sync=datetime.utcnow()
                            )
                            db.session.add(new_item)
                            imported_count += 1
                            log_task(f"  → Created new item (SKU: {new_sku})")
                        else:
                            # update_existing mode: skip new items
                            skipped_count += 1
                            log_task(f"  → Skipped (update_existing mode only updates)")

                    # Update progress every item
                    job.processed_items = idx + 1
                    job.imported_count = imported_count
                    job.updated_count = updated_count
                    job.skipped_count = skipped_count
                    job.error_count = error_count

                    # Commit every 10 items
                    if (idx + 1) % 10 == 0:
                        db.session.commit()
                        log_task(f"Progress: {idx + 1}/{len(ebay_items)} - Committed")

                        # Update Celery task state
                        self.update_state(
                            state='PROGRESS',
                            meta={
                                'current': idx + 1,
                                'total': len(ebay_items),
                                'imported': imported_count,
                                'updated': updated_count,
                                'skipped': skipped_count,
                                'errors': error_count
                            }
                        )

                except Exception as item_error:
                    error_count += 1
                    log_task(f"ERROR processing item {idx + 1}: {str(item_error)}")
                    import traceback
                    log_task(f"Traceback: {traceback.format_exc()}")

            # Final commit
            db.session.commit()

            # Mark job as completed
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            job.processed_items = len(ebay_items)
            job.imported_count = imported_count
            job.updated_count = updated_count
            job.skipped_count = skipped_count
            job.error_count = error_count
            db.session.commit()

            log_task(f"=== Import completed ===")
            log_task(f"Imported: {imported_count}, Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}")

            return {
                'status': 'completed',
                'imported': imported_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'errors': error_count,
                'total': len(ebay_items)
            }

        except Exception as e:
            log_task(f"FATAL ERROR in import task: {str(e)}")
            import traceback
            log_task(f"Traceback: {traceback.format_exc()}")

            # Mark job as failed
            job.status = 'failed'
            job.completed_at = datetime.utcnow()
            job.error_message = str(e)
            db.session.commit()

            raise  # Re-raise to mark Celery task as failed


@celery.task(bind=True, name='qventory.tasks.import_ebay_sales')
def import_ebay_sales(self, user_id, days_back=None):
    """
    Background task to import eBay sales/orders

    Args:
        user_id: Qventory user ID
        days_back: How many days back to fetch orders (None = lifetime/all orders)

    Returns:
        dict with import results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.sale import Sale
        from qventory.models.item import Item
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.helpers.ebay_inventory import get_ebay_orders
        from dateutil import parser as date_parser
        from datetime import datetime, timedelta

        if days_back:
            log_task(f"Starting eBay sales import for user {user_id}, last {days_back} days")
        else:
            log_task(f"Starting eBay sales import for user {user_id}, ALL TIME (lifetime)")

        try:
            # Get eBay credentials to check for store subscription
            ebay_cred = MarketplaceCredential.query.filter_by(
                user_id=user_id,
                marketplace='ebay'
            ).first()

            ebay_store_monthly_fee = ebay_cred.ebay_store_subscription if ebay_cred else 0.0

            # Fetch orders from eBay
            orders = get_ebay_orders(user_id, days_back=days_back)
            log_task(f"Fetched {len(orders)} orders from eBay")

            if ebay_store_monthly_fee > 0:
                log_task(f"eBay Store Subscription detected: ${ebay_store_monthly_fee}/month")

            imported_count = 0
            updated_count = 0
            skipped_count = 0

            for order in orders:
                try:
                    order_id = order.get('orderId')
                    order_status = order.get('orderFulfillmentStatus', 'UNKNOWN')

                    # Only process completed/paid orders
                    if order_status not in ['FULFILLED', 'IN_PROGRESS']:
                        skipped_count += 1
                        continue

                    # Get order pricing
                    pricing_summary = order.get('pricingSummary', {})
                    total_price = float(pricing_summary.get('total', {}).get('value', 0))

                    # Get order creation date
                    creation_date_str = order.get('creationDate', '')
                    sold_at = date_parser.parse(creation_date_str) if creation_date_str else datetime.utcnow()

                    # Get buyer info
                    buyer = order.get('buyer', {})
                    buyer_username = buyer.get('username', '')

                    # Process each line item in the order
                    line_items = order.get('lineItems', [])

                    for line_item in line_items:
                        sku = line_item.get('sku', '')
                        title = line_item.get('title', 'Unknown Item')
                        line_item_id = line_item.get('lineItemId', '')

                        # Get price for this line item
                        line_total = float(line_item.get('total', {}).get('value', 0))

                        # Extract shipping details from order
                        shipping_cost = 0.0
                        shipping_charged = 0.0

                        # Get what buyer paid for shipping (from line item)
                        line_item_cost = line_item.get('lineItemCost', {})
                        if line_item_cost:
                            shipping_charged = float(line_item_cost.get('shippingCost', {}).get('value', 0))

                        # Alternative: try deliveryCost from line item
                        if shipping_charged == 0.0:
                            delivery_cost = line_item.get('deliveryCost', {})
                            if delivery_cost:
                                shipping_charged = float(delivery_cost.get('value', 0))

                        # Actual shipping cost seller paid (not in Order API)
                        # eBay Order API doesn't provide actual shipping label cost
                        # This needs to come from Shipping Fulfillment API or manual entry
                        # For now, estimate 70% of charged amount or leave at 0
                        shipping_cost = 0.0  # User can edit manually

                        # Calculate eBay fees (approximate - eBay doesn't provide exact fees in Order API)
                        # Final value fee: ~13.25% for most categories (can vary 10-15%)
                        # This is an approximation - for exact fees, use eBay Finance API
                        marketplace_fee = line_total * 0.1325  # ~13.25% eBay final value fee

                        # Payment processing fee (eBay Managed Payments: ~2.9% + $0.30)
                        payment_fee = line_total * 0.029 + 0.30

                        # Calculate prorated store subscription fee (if any)
                        # Distribute monthly fee across all sales in the month
                        store_fee_per_sale = 0.0
                        if ebay_store_monthly_fee > 0 and len(orders) > 0:
                            # Simple approach: divide by total orders in this import
                            # More accurate would be: monthly fee / sales in that month
                            store_fee_per_sale = ebay_store_monthly_fee / len(orders)

                        # Try to find matching item in Qventory
                        item = None
                        if sku:
                            item = Item.query.filter_by(user_id=user_id, ebay_sku=sku).first()

                        if not item and title:
                            item = Item.query.filter_by(user_id=user_id, title=title).first()

                        # Check if sale already exists
                        existing_sale = Sale.query.filter_by(
                            user_id=user_id,
                            marketplace='ebay',
                            marketplace_order_id=order_id,
                            item_sku=sku
                        ).first()

                        if existing_sale:
                            # Update existing sale
                            existing_sale.sold_price = line_total
                            existing_sale.status = 'completed' if order_status == 'FULFILLED' else 'shipped'
                            existing_sale.marketplace_fee = marketplace_fee
                            existing_sale.payment_processing_fee = payment_fee
                            existing_sale.shipping_charged = shipping_charged
                            existing_sale.other_fees = store_fee_per_sale  # Store subscription prorate
                            existing_sale.updated_at = datetime.utcnow()

                            # Update item cost if available
                            if item and item.item_cost:
                                existing_sale.item_cost = item.item_cost

                            existing_sale.calculate_profit()
                            updated_count += 1
                            log_task(f"  Updated sale: {title[:50]}")
                        else:
                            # Create new sale
                            new_sale = Sale(
                                user_id=user_id,
                                item_id=item.id if item else None,
                                marketplace='ebay',
                                marketplace_order_id=order_id,
                                item_title=title,
                                item_sku=sku,
                                sold_price=line_total,
                                item_cost=item.item_cost if item else None,
                                marketplace_fee=marketplace_fee,
                                payment_processing_fee=payment_fee,
                                shipping_cost=shipping_cost,
                                shipping_charged=shipping_charged,
                                other_fees=store_fee_per_sale,  # Store subscription prorate
                                sold_at=sold_at,
                                status='completed' if order_status == 'FULFILLED' else 'shipped',
                                buyer_username=buyer_username,
                                ebay_transaction_id=line_item_id,
                                ebay_buyer_username=buyer_username
                            )

                            new_sale.calculate_profit()
                            db.session.add(new_sale)
                            imported_count += 1
                            total_fees = marketplace_fee + payment_fee + store_fee_per_sale
                            log_task(f"  Imported sale: {title[:50]} - ${line_total} (Fees: ${total_fees:.2f}, Ship: ${shipping_charged:.2f})")

                except Exception as item_error:
                    log_task(f"  ERROR processing line item: {str(item_error)}")
                    continue

            # Commit all sales
            db.session.commit()

            log_task(f"✅ Sales import complete: {imported_count} new, {updated_count} updated, {skipped_count} skipped")

            return {
                'success': True,
                'imported': imported_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'total_orders': len(orders)
            }

        except Exception as e:
            log_task(f"✗ ERROR importing eBay sales: {str(e)}")
            import traceback
            log_task(f"Traceback: {traceback.format_exc()}")
            db.session.rollback()
            raise
