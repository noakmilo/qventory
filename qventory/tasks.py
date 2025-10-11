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
        from qventory.helpers.ebay_inventory import get_all_inventory, parse_ebay_inventory_item, get_listing_time_details
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

                    # Parse eBay item WITHOUT image processing first (to avoid wasting Cloudinary quota)
                    parsed = parse_ebay_inventory_item(ebay_item, process_images=False)
                    ebay_sku = parsed.get('ebay_sku', '')
                    ebay_title = parsed.get('title', '')

                    log_task(f"  Title: {ebay_title[:50]}")

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

                    start_time = None
                    end_time = None
                    if ebay_listing_id:
                        listing_times = get_listing_time_details(user_id, ebay_listing_id)
                        start_time = listing_times.get('start_time')
                        end_time = listing_times.get('end_time')
                        if start_time:
                            parsed['listing_start_time'] = start_time
                            ebay_item['listing_start_time'] = start_time
                        if end_time:
                            parsed['listing_end_time'] = end_time
                            ebay_item['listing_end_time'] = end_time

                    if existing_item:
                        log_task(f"  ✓ Match found (method: {match_method}, Qventory ID: {existing_item.id}, mode: {import_mode})")

                        if import_mode in ['update_existing', 'sync_all']:
                            # NOW process images since we're actually updating
                            parsed_with_images = parse_ebay_inventory_item(ebay_item, process_images=True)
                            log_task(f"  Image processed: {parsed_with_images.get('item_thumb', 'N/A')[:80]}")
                            if not start_time and parsed_with_images.get('listing_start_time'):
                                start_time = parsed_with_images.get('listing_start_time')
                            if not end_time and parsed_with_images.get('listing_end_time'):
                                end_time = parsed_with_images.get('listing_end_time')

                            # Update eBay-specific fields
                            existing_item.synced_from_ebay = True
                            existing_item.last_ebay_sync = datetime.utcnow()

                            if parsed_with_images.get('ebay_listing_id'):
                                existing_item.ebay_listing_id = parsed_with_images['ebay_listing_id']
                            if parsed_with_images.get('ebay_url'):
                                existing_item.ebay_url = parsed_with_images['ebay_url']
                            if parsed_with_images.get('item_price'):
                                existing_item.item_price = parsed_with_images['item_price']
                            if parsed_with_images.get('item_thumb'):
                                existing_item.item_thumb = parsed_with_images['item_thumb']  # Update with Cloudinary URL
                            if ebay_sku and not existing_item.ebay_sku:
                                existing_item.ebay_sku = ebay_sku
                            if start_time:
                                existing_item.listing_date = start_time.date()

                            updated_count += 1
                            log_task(f"  → Updated existing item")
                        else:
                            # new_only mode: skip items that already exist (NO image processing)
                            skipped_count += 1
                            log_task(f"  → Skipped (already in Qventory, no image uploaded)")
                    else:
                        log_task(f"  New item from eBay")

                        if import_mode in ['new_only', 'sync_all']:
                            # NOW process images since we're importing a new item
                            parsed_with_images = parse_ebay_inventory_item(ebay_item, process_images=True)
                            log_task(f"  Image processed: {parsed_with_images.get('item_thumb', 'N/A')[:80]}")
                            if not start_time and parsed_with_images.get('listing_start_time'):
                                start_time = parsed_with_images.get('listing_start_time')
                            if not end_time and parsed_with_images.get('listing_end_time'):
                                end_time = parsed_with_images.get('listing_end_time')

                            new_sku = generate_sku()
                            new_item = Item(
                                user_id=user_id,
                                sku=new_sku,
                                title=ebay_title,
                                item_thumb=parsed_with_images.get('item_thumb'),  # Cloudinary URL
                                ebay_sku=ebay_sku,
                                ebay_listing_id=parsed_with_images.get('ebay_listing_id'),
                                ebay_url=parsed_with_images.get('ebay_url'),
                                item_price=parsed_with_images.get('item_price'),
                                listing_date=start_time.date() if start_time else None,
                                # Import location from eBay Custom SKU if detected
                                A=parsed_with_images.get('location_A'),
                                B=parsed_with_images.get('location_B'),
                                S=parsed_with_images.get('location_S'),
                                C=parsed_with_images.get('location_C'),
                                location_code=parsed_with_images.get('location_code'),
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

                        # Update Celery task state (only if we have a valid task_id)
                        if hasattr(self, 'request') and self.request.id:
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

            # TEMPORAL FIX: Use getattr to safely access ebay_store_subscription
            # In case migration hasn't been applied yet
            ebay_store_monthly_fee = getattr(ebay_cred, 'ebay_store_subscription', 0.0) if ebay_cred else 0.0

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

                        # Try to get eBay listing ID from lineItem
                        ebay_listing_id = line_item.get('legacyItemId') or line_item.get('listingMarketplaceId')

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

                        # Extract ACTUAL shipping cost and fulfillment data (what seller paid for label)
                        # This is available when seller buys shipping label through eBay
                        shipping_cost = 0.0
                        tracking_number = None
                        carrier = None
                        shipped_at = None
                        delivered_at = None

                        fulfillment_instructions = order.get('fulfillmentStartInstructions', [])
                        if fulfillment_instructions:
                            shipping_step = fulfillment_instructions[0].get('shippingStep', {})
                            shipment_details = shipping_step.get('shipmentDetails', {})

                            # Get actual shipping cost
                            actual_shipping = shipment_details.get('actualShippingCost', {})
                            if actual_shipping:
                                shipping_cost = float(actual_shipping.get('value', 0))
                                log_task(f"    Actual shipping cost from eBay: ${shipping_cost}")

                            # Get tracking number and carrier
                            tracking_number = shipment_details.get('trackingNumber')
                            carrier = shipment_details.get('shippingCarrierCode')

                            # Get shipped date
                            shipped_date_str = shipment_details.get('shippedDate') or shipment_details.get('actualShipDate')
                            if shipped_date_str:
                                try:
                                    shipped_at = date_parser.parse(shipped_date_str)
                                    log_task(f"    Shipped: {shipped_at}")
                                except:
                                    pass

                            # Get delivery date (if available)
                            delivery_date_str = shipment_details.get('deliveredDate') or shipment_details.get('actualDeliveryDate')
                            if delivery_date_str:
                                try:
                                    delivered_at = date_parser.parse(delivery_date_str)
                                    log_task(f"    Delivered: {delivered_at}")
                                except:
                                    pass

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

                        # Try to find matching item in Qventory (multiple strategies)
                        item = None
                        match_method = None

                        # Strategy 1: Match by eBay Listing ID (most reliable)
                        if ebay_listing_id:
                            item = Item.query.filter_by(
                                user_id=user_id,
                                ebay_listing_id=ebay_listing_id
                            ).first()
                            if item:
                                match_method = "ebay_listing_id"

                        # Strategy 2: Match by eBay SKU
                        if not item and sku:
                            item = Item.query.filter_by(user_id=user_id, ebay_sku=sku).first()
                            if item:
                                match_method = "ebay_sku"

                        # Strategy 3: Match by exact title
                        if not item and title:
                            item = Item.query.filter_by(user_id=user_id, title=title).first()
                            if item:
                                match_method = "exact_title"

                        if item:
                            log_task(f"  ✓ Matched item (method: {match_method}, item_id: {item.id})")

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
                            existing_sale.shipping_cost = shipping_cost
                            existing_sale.shipping_charged = shipping_charged
                            existing_sale.other_fees = store_fee_per_sale  # Store subscription prorate
                            existing_sale.updated_at = datetime.utcnow()

                            # Update item_id if we found a match and it wasn't set before
                            if item and not existing_sale.item_id:
                                existing_sale.item_id = item.id
                                log_task(f"    → Linked sale to item {item.id}")

                            # Update fulfillment data
                            if tracking_number:
                                existing_sale.tracking_number = tracking_number
                            if carrier:
                                existing_sale.carrier = carrier
                            if shipped_at:
                                existing_sale.shipped_at = shipped_at
                            if delivered_at:
                                existing_sale.delivered_at = delivered_at

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
                                shipped_at=shipped_at,
                                delivered_at=delivered_at,
                                tracking_number=tracking_number,
                                carrier=carrier,
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


@celery.task(bind=True, name='qventory.tasks.import_ebay_complete')
def import_ebay_complete(self, user_id, import_mode='new_only', listing_status='ACTIVE', days_back=None):
    """
    Complete eBay import: Inventory + Sales in one task

    This replaces the need to run two separate imports.

    Args:
        user_id: Qventory user ID
        import_mode: 'new_only', 'update_existing', or 'sync_all' (for inventory)
        listing_status: 'ACTIVE' or 'ALL' (for inventory)
        days_back: How many days back to fetch sales (None = all time)

    Returns:
        dict with combined import results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.import_job import ImportJob

        log_task(f"=== Starting COMPLETE eBay import for user {user_id} ===")
        log_task(f"Inventory mode: {import_mode}, Status: {listing_status}")
        log_task(f"Sales: last {days_back} days" if days_back else "Sales: ALL TIME")

        # Create ImportJob to track overall progress
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
            # STEP 1: Import Inventory (Active Listings)
            log_task("\n📦 STEP 1/2: Importing active inventory...")

            # Call the task's run() method to execute synchronously in the same context
            inventory_result = import_ebay_inventory.run(
                user_id,
                import_mode,
                listing_status
            )

            log_task(f"✅ Inventory imported:")
            log_task(f"   - Imported: {inventory_result.get('imported', 0)}")
            log_task(f"   - Updated: {inventory_result.get('updated', 0)}")
            log_task(f"   - Skipped: {inventory_result.get('skipped', 0)}")

            # STEP 2: Import Sales/Orders
            log_task("\n💰 STEP 2/2: Importing sales/orders...")

            sales_result = import_ebay_sales.run(
                user_id,
                days_back
            )

            log_task(f"✅ Sales imported:")
            log_task(f"   - Imported: {sales_result.get('imported', 0)}")
            log_task(f"   - Updated: {sales_result.get('updated', 0)}")
            log_task(f"   - Skipped: {sales_result.get('skipped', 0)}")

            # Update job with combined stats
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            job.total_items = inventory_result.get('total', 0)
            job.imported_count = inventory_result.get('imported', 0) + sales_result.get('imported', 0)
            job.updated_count = inventory_result.get('updated', 0) + sales_result.get('updated', 0)
            job.skipped_count = inventory_result.get('skipped', 0) + sales_result.get('skipped', 0)
            db.session.commit()

            log_task("\n🎉 === COMPLETE import finished successfully ===")

            return {
                'success': True,
                'inventory': inventory_result,
                'sales': sales_result,
                'summary': {
                    'total_imported': job.imported_count,
                    'total_updated': job.updated_count,
                    'total_skipped': job.skipped_count
                }
            }

        except Exception as e:
            log_task(f"\n✗ ERROR in complete import: {str(e)}")
            import traceback
            log_task(f"Traceback: {traceback.format_exc()}")

            job.status = 'failed'
            job.completed_at = datetime.utcnow()
            job.error_message = str(e)
            db.session.commit()

            raise
