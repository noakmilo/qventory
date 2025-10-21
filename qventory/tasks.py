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
        from qventory.models.failed_import import FailedImport
        from qventory.models.user import User
        from qventory.helpers.ebay_inventory import get_all_inventory, parse_ebay_inventory_item, get_listing_time_details, get_active_listings_trading_api
        from qventory.helpers import generate_sku

        log_task(f"=== Starting eBay import for user {user_id} ===")
        log_task(f"Mode: {import_mode}, Status: {listing_status}")
        log_task(f"Task ID: {self.request.id}")

        # Check user's plan limits
        user = User.query.get(user_id)
        if not user:
            raise Exception(f"User {user_id} not found")

        items_remaining = user.items_remaining()
        log_task(f"User plan limits - Items remaining: {items_remaining}")

        # IMPORTANT: In sync_all mode, we allow syncing ALL eBay inventory regardless of plan limits
        # because the user is syncing their EXISTING eBay inventory, not adding arbitrary new items
        if import_mode == 'sync_all':
            max_new_items_allowed = None  # No limit for full sync
            log_task(f"Mode: sync_all - No item limit (syncing existing eBay inventory)")
        else:
            if items_remaining is not None and items_remaining <= 0:
                raise Exception(f"Cannot import: User has reached plan limit (0 items remaining)")
            max_new_items_allowed = items_remaining  # Track how many NEW items we can import
            log_task(f"Mode: {import_mode} - Max new items allowed: {max_new_items_allowed}")

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

            # Fetch inventory from eBay using Trading API with failure collection
            log_task("Fetching inventory from eBay API...")
            ebay_items, failed_items = get_active_listings_trading_api(user_id, max_items=1000, collect_failures=True)
            log_task(f"Fetched {len(ebay_items)} items from eBay")
            log_task(f"Failed to parse: {len(failed_items)} items")

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

                    # Second try: Match by exact title (least reliable)
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
                            if start_time:
                                existing_item.listing_date = start_time.date()

                            # Update title if changed (this ensures correct titles)
                            if parsed_with_images.get('title'):
                                existing_item.title = parsed_with_images['title']

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
                            # Check if user has reached their quota for NEW items
                            if max_new_items_allowed is not None and imported_count >= max_new_items_allowed:
                                skipped_count += 1
                                log_task(f"  → Skipped (plan limit reached: {max_new_items_allowed} items)")
                                continue

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
                            log_task(f"  → Created new item (SKU: {new_sku}) [{imported_count}/{max_new_items_allowed if max_new_items_allowed is not None else 'unlimited'}]")
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

            # DETAILED SUMMARY LOGGING
            log_task(f"")
            log_task(f"=" * 80)
            log_task(f"IMPORT SUMMARY")
            log_task(f"=" * 80)
            log_task(f"Total items fetched from eBay: {len(ebay_items)}")
            log_task(f"")
            log_task(f"BREAKDOWN:")
            log_task(f"  ✅ Imported (new items):     {imported_count}")
            log_task(f"  🔄 Updated (existing items): {updated_count}")
            log_task(f"  ⏭  Skipped:                  {skipped_count}")
            log_task(f"  ❌ Errors during processing: {error_count}")
            log_task(f"  ⚠️  Failed to parse (eBay):  {len(failed_items)}")
            log_task(f"")
            log_task(f"TOTAL ACCOUNTED: {imported_count + updated_count + skipped_count + error_count + len(failed_items)}/{len(ebay_items)}")

            missing = len(ebay_items) - (imported_count + updated_count + skipped_count + error_count + len(failed_items))
            if missing != 0:
                log_task(f"⚠️  MISSING/UNACCOUNTED: {missing} items")

            log_task(f"=" * 80)

            # Store failed items in database for retry
            log_task(f"Storing {len(failed_items)} failed items for retry...")
            failed_stored = 0
            for failed_item in failed_items:
                try:
                    # Check if this failed item already exists (avoid duplicates)
                    existing_failed = None
                    if failed_item.get('ebay_listing_id'):
                        existing_failed = FailedImport.query.filter_by(
                            user_id=user_id,
                            ebay_listing_id=failed_item['ebay_listing_id'],
                            resolved=False
                        ).first()

                    if existing_failed:
                        # Update existing failed import
                        existing_failed.retry_count += 1
                        existing_failed.last_retry_at = datetime.utcnow()
                        existing_failed.error_message = failed_item.get('error_message')
                        existing_failed.raw_data = failed_item.get('raw_data')
                        existing_failed.updated_at = datetime.utcnow()
                        log_task(f"  Updated existing failed import for listing {failed_item.get('ebay_listing_id')}")
                    else:
                        # Create new failed import record
                        failed_record = FailedImport(
                            user_id=user_id,
                            import_job_id=job.id,
                            ebay_listing_id=failed_item.get('ebay_listing_id'),
                            ebay_title=failed_item.get('ebay_title'),
                            ebay_sku=failed_item.get('ebay_sku'),
                            error_type=failed_item.get('error_type', 'parsing_error'),
                            error_message=failed_item.get('error_message'),
                            raw_data=failed_item.get('raw_data'),
                            retry_count=0,
                            resolved=False
                        )
                        db.session.add(failed_record)
                        failed_stored += 1
                except Exception as e:
                    log_task(f"  ERROR storing failed item: {str(e)}")

            db.session.commit()
            log_task(f"✓ Stored {failed_stored} new failed items (total with updates: {len(failed_items)})")

            # Check if plan limit was reached before committing job updates
            plan_limit_reached = (max_new_items_allowed is not None and
                                imported_count >= max_new_items_allowed and
                                skipped_count > 0)

            if plan_limit_reached:
                log_task(f"⚠️  PLAN LIMIT REACHED: Imported {imported_count} items (limit: {max_new_items_allowed})")
                job.error_message = f"Plan limit reached. Imported {imported_count}/{max_new_items_allowed} items. Upgrade to import more."
            else:
                # Clear previous plan-limit warning if this run completed under the limit
                if job.error_message and 'Plan limit reached' in job.error_message:
                    job.error_message = None

            # Mark job as completed
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            job.processed_items = len(ebay_items)
            job.imported_count = imported_count
            job.updated_count = updated_count
            job.skipped_count = skipped_count
            job.error_count = error_count + len(failed_items)  # Include parsing failures
            db.session.commit()

            log_task(f"=== Import completed ===")
            log_task(f"Imported: {imported_count}, Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}")
            log_task(f"Failed to parse: {len(failed_items)} (stored for retry)")

            return {
                'status': 'completed',
                'imported': imported_count,
                'updated': updated_count,
                'skipped': skipped_count,
                'errors': error_count,
                'plan_limit_reached': plan_limit_reached,
                'max_items_allowed': max_new_items_allowed,
                'failed_items': len(failed_items),
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
        from qventory.helpers.ebay_inventory import fetch_ebay_sold_orders
        from dateutil import parser as date_parser
        from datetime import datetime, timedelta

        # Ensure days_back is properly typed (can arrive as string from Celery serialization)
        if days_back is not None:
            try:
                days_back = int(days_back)
                if days_back <= 0:
                    days_back = None
            except (ValueError, TypeError):
                days_back = None

        if days_back:
            log_task(f"Starting eBay sales import for user {user_id}, last {days_back} days")
        else:
            log_task(f"Starting eBay sales import for user {user_id}, ALL TIME (full history)")

        try:
            # Get eBay credentials to check for store subscription
            ebay_cred = MarketplaceCredential.query.filter_by(
                user_id=user_id,
                marketplace='ebay'
            ).first()

            # TEMPORAL FIX: Use getattr to safely access ebay_store_subscription
            # In case migration hasn't been applied yet
            ebay_store_monthly_fee = getattr(ebay_cred, 'ebay_store_subscription', 0.0) if ebay_cred else 0.0

            # Fetch orders from eBay using the improved function that handles full history
            # This function automatically iterates in 90-day windows when days_back=None
            result = fetch_ebay_sold_orders(user_id, days_back=days_back)

            if not result['success']:
                raise Exception(result.get('error', 'Failed to fetch eBay orders'))

            orders = result['orders']
            log_task(f"Fetched {len(orders)} orders from eBay (scanned {result.get('fetched', 0)} total records)")

            if ebay_store_monthly_fee > 0:
                log_task(f"eBay Store Subscription detected: ${ebay_store_monthly_fee}/month")

            imported_count = 0
            updated_count = 0
            skipped_count = 0

            # Orders are already parsed by fetch_ebay_sold_orders into sale-ready format
            for sale_data in orders:
                try:
                    if not sale_data:
                        skipped_count += 1
                        continue

                    # Extract data from parsed order (already in normalized format)
                    order_id = sale_data.get('marketplace_order_id')
                    title = sale_data.get('item_title', 'Unknown Item')
                    sku = sale_data.get('item_sku', '')
                    sold_price = sale_data.get('sold_price', 0)
                    shipping_cost = sale_data.get('shipping_cost', 0)
                    buyer_username = sale_data.get('buyer_username', '')
                    tracking_number = sale_data.get('tracking_number')
                    carrier = sale_data.get('carrier')
                    shipped_at = sale_data.get('shipped_at')
                    delivered_at = sale_data.get('delivered_at')
                    sold_at = sale_data.get('sold_at', datetime.utcnow())
                    status = sale_data.get('status', 'pending')
                    ebay_transaction_id = sale_data.get('ebay_transaction_id')

                    # Calculate eBay fees (approximate)
                    marketplace_fee = sold_price * 0.1325  # ~13.25% eBay final value fee
                    payment_fee = sold_price * 0.029 + 0.30  # Payment processing

                    # Calculate prorated store subscription fee
                    store_fee_per_sale = 0.0
                    if ebay_store_monthly_fee > 0 and len(orders) > 0:
                        store_fee_per_sale = ebay_store_monthly_fee / len(orders)

                    # Try to find matching item in Qventory (multiple strategies)
                    item = None
                    match_method = None

                    # Strategy 1: Match by SKU
                    if sku:
                        item = Item.query.filter_by(user_id=user_id, ebay_sku=sku).first()
                        if item:
                            match_method = "ebay_sku"

                    # Strategy 2: Match by exact title
                    if not item and title:
                        item = Item.query.filter_by(user_id=user_id, title=title).first()
                        if item:
                            match_method = "exact_title"

                    if item:
                        log_task(f"  ✓ Matched item (method: {match_method}, item_id: {item.id})")
                    else:
                        log_task(f"  ⚠️  No match found for: sku={sku}, title={title[:40]}")

                    # Check if sale already exists
                    existing_sale = Sale.query.filter_by(
                        user_id=user_id,
                        marketplace='ebay',
                        marketplace_order_id=order_id,
                        item_sku=sku
                    ).first()

                    if existing_sale:
                        # Update existing sale
                        existing_sale.sold_price = sold_price
                        existing_sale.status = status
                        existing_sale.marketplace_fee = marketplace_fee
                        existing_sale.payment_processing_fee = payment_fee
                        existing_sale.shipping_cost = shipping_cost
                        existing_sale.other_fees = store_fee_per_sale
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
                            sold_price=sold_price,
                            item_cost=item.item_cost if item else None,
                            marketplace_fee=marketplace_fee,
                            payment_processing_fee=payment_fee,
                            shipping_cost=shipping_cost,
                            other_fees=store_fee_per_sale,
                            sold_at=sold_at,
                            shipped_at=shipped_at,
                            delivered_at=delivered_at,
                            tracking_number=tracking_number,
                            carrier=carrier,
                            status=status,
                            buyer_username=buyer_username,
                            ebay_transaction_id=ebay_transaction_id,
                            ebay_buyer_username=buyer_username
                        )

                        new_sale.calculate_profit()
                        db.session.add(new_sale)
                        imported_count += 1
                        total_fees = marketplace_fee + payment_fee + store_fee_per_sale
                        log_task(f"  Imported sale: {title[:50]} - ${sold_price} (Fees: ${total_fees:.2f})")

                except Exception as item_error:
                    log_task(f"  ERROR processing sale: {str(item_error)}")
                    import traceback
                    log_task(f"  Traceback: {traceback.format_exc()}")
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

            # Create notification for user
            from qventory.models.notification import Notification
            total_items = job.imported_count + job.updated_count
            Notification.create_notification(
                user_id=user_id,
                type='success',
                title=f'eBay import completed successfully!',
                message=f'Imported {job.imported_count} new items, updated {job.updated_count} existing items.',
                link_url='/dashboard',
                link_text='View Inventory',
                source='import'
            )

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

            # Create error notification
            from qventory.models.notification import Notification
            Notification.create_notification(
                user_id=user_id,
                type='error',
                title='eBay import failed',
                message=f'Error: {str(e)}',
                link_url='/import/ebay',
                link_text='Try Again',
                source='import'
            )

            raise


@celery.task(bind=True, name='qventory.tasks.retry_failed_imports')
def retry_failed_imports(self, user_id, failed_import_ids=None):
    """
    Retry importing items that previously failed to parse

    Args:
        user_id: Qventory user ID
        failed_import_ids: List of specific FailedImport IDs to retry (None = retry all unresolved)

    Returns:
        dict with retry results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.failed_import import FailedImport
        from qventory.models.item import Item
        from qventory.helpers import generate_sku
        from qventory.helpers.ebay_inventory import get_listing_time_details
        import xml.etree.ElementTree as ET

        log_task(f"=== Starting retry of failed imports for user {user_id} ===")

        # Get failed imports to retry
        if failed_import_ids:
            failed_imports = FailedImport.query.filter(
                FailedImport.id.in_(failed_import_ids),
                FailedImport.user_id == user_id,
                FailedImport.resolved == False
            ).all()
            log_task(f"Retrying {len(failed_imports)} specific failed imports")
        else:
            failed_imports = FailedImport.get_unresolved_for_user(user_id)
            log_task(f"Retrying all {len(failed_imports)} unresolved failed imports")

        if not failed_imports:
            log_task("No failed imports to retry")
            return {
                'success': True,
                'retried': 0,
                'resolved': 0,
                'still_failed': 0
            }

        resolved_count = 0
        still_failed_count = 0

        for failed_import in failed_imports:
            try:
                log_task(f"Retrying listing {failed_import.ebay_listing_id}: {failed_import.ebay_title[:50] if failed_import.ebay_title else 'N/A'}")

                # Try to parse the raw XML data again
                if not failed_import.raw_data:
                    log_task(f"  No raw data available, skipping")
                    still_failed_count += 1
                    continue

                # Parse the XML
                ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
                item_elem = ET.fromstring(failed_import.raw_data)

                # Extract item data (same logic as in get_active_listings_trading_api)
                item_id = item_elem.find('ebay:ItemID', ns)
                title = item_elem.find('ebay:Title', ns)

                # Price
                selling_status = item_elem.find('ebay:SellingStatus', ns)
                current_price = selling_status.find('ebay:CurrentPrice', ns) if selling_status is not None else None
                price = float(current_price.text) if current_price is not None else 0

                # Quantity
                quantity_elem = item_elem.find('ebay:Quantity', ns)
                quantity = int(quantity_elem.text) if quantity_elem is not None else 1

                # SKU
                sku_elem = item_elem.find('ebay:SKU', ns)
                sku = sku_elem.text if sku_elem is not None else ''

                # Image
                picture_details = item_elem.find('ebay:PictureDetails', ns)
                image_url = None
                if picture_details is not None:
                    gallery_url = picture_details.find('ebay:GalleryURL', ns)
                    if gallery_url is not None:
                        image_url = gallery_url.text

                # Listing times
                start_elem = item_elem.find('ebay:ListingDetails/ebay:StartTime', ns)
                if start_elem is None:
                    start_elem = item_elem.find('ebay:StartTime', ns)
                end_elem = item_elem.find('ebay:ListingDetails/ebay:EndTime', ns)
                if end_elem is None:
                    end_elem = item_elem.find('ebay:EndTime', ns)

                from qventory.helpers.ebay_inventory import _parse_ebay_datetime
                start_time = _parse_ebay_datetime(start_elem.text if start_elem is not None else None)
                end_time = _parse_ebay_datetime(end_elem.text if end_elem is not None else None)

                # Check if item already exists
                existing_item = None
                if failed_import.ebay_listing_id:
                    existing_item = Item.query.filter_by(
                        user_id=user_id,
                        ebay_listing_id=failed_import.ebay_listing_id
                    ).first()

                if existing_item:
                    log_task(f"  Item already exists in database (ID: {existing_item.id}), marking as resolved")
                    failed_import.resolved = True
                    failed_import.resolved_at = datetime.utcnow()
                    resolved_count += 1
                else:
                    # Create new item
                    from qventory.helpers.image_processor import download_and_upload_image
                    item_thumb = None
                    if image_url:
                        log_task(f"  Processing image...")
                        item_thumb = download_and_upload_image(image_url, target_size_kb=2, max_dimension=400)
                        if not item_thumb:
                            item_thumb = image_url  # Fallback to original

                    new_sku = generate_sku()
                    new_item = Item(
                        user_id=user_id,
                        sku=new_sku,
                        title=title.text if title is not None else 'Unknown',
                        item_thumb=item_thumb,
                        ebay_sku=sku,
                        ebay_listing_id=item_id.text if item_id is not None else '',
                        ebay_url=f"https://www.ebay.com/itm/{item_id.text}" if item_id is not None else None,
                        item_price=price,
                        listing_date=start_time.date() if start_time else None,
                        synced_from_ebay=True,
                        last_ebay_sync=datetime.utcnow()
                    )
                    db.session.add(new_item)

                    # Mark as resolved
                    failed_import.resolved = True
                    failed_import.resolved_at = datetime.utcnow()
                    resolved_count += 1

                    log_task(f"  ✓ Successfully imported item (SKU: {new_sku})")

                # Update retry count
                failed_import.retry_count += 1
                failed_import.last_retry_at = datetime.utcnow()

                # Commit every item
                db.session.commit()

            except Exception as e:
                log_task(f"  ✗ Still failed: {str(e)}")
                failed_import.retry_count += 1
                failed_import.last_retry_at = datetime.utcnow()
                failed_import.error_message = f"Retry {failed_import.retry_count}: {str(e)}"
                db.session.commit()
                still_failed_count += 1

        log_task(f"=== Retry completed ===")
        log_task(f"Resolved: {resolved_count}, Still failed: {still_failed_count}")

        return {
            'success': True,
            'retried': len(failed_imports),
            'resolved': resolved_count,
            'still_failed': still_failed_count
        }


@celery.task(bind=True, name='qventory.tasks.rematch_sales_to_items')
def rematch_sales_to_items(self, user_id):
    """
    Re-attempt matching sales without item_id to items in inventory
    This is useful for historical sales that couldn't be matched initially

    Args:
        user_id: Qventory user ID

    Returns:
        dict with rematch results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.sale import Sale
        from qventory.models.item import Item

        log_task(f"=== Starting rematch of unlinked sales for user {user_id} ===")

        # Get all sales without item_id
        unlinked_sales = Sale.query.filter_by(
            user_id=user_id,
            item_id=None
        ).all()

        log_task(f"Found {len(unlinked_sales)} unlinked sales")

        matched_count = 0
        still_unmatched = 0

        for sale in unlinked_sales:
            try:
                # Try to find matching item (same strategies as import)
                item = None
                match_method = None

                # Extract identifiers from sale
                ebay_listing_id = None
                if sale.marketplace == 'ebay' and sale.marketplace_order_id:
                    # Try to extract listing ID from eBay transaction
                    # Note: This might not be available in older sales
                    pass

                sku = sale.item_sku
                title = sale.item_title

                # Strategy 1: Match by eBay Listing ID (if available)
                # We don't have this in Sale model, so skip

                # Strategy 2: Match by SKU
                if not item and sku:
                    # Try eBay SKU first
                    item = Item.query.filter_by(user_id=user_id, ebay_sku=sku).first()
                    if item:
                        match_method = "ebay_sku"
                    else:
                        # Try Qventory SKU
                        item = Item.query.filter_by(user_id=user_id, sku=sku).first()
                        if item:
                            match_method = "qventory_sku"

                # Strategy 3: Match by exact title
                if not item and title:
                    item = Item.query.filter_by(user_id=user_id, title=title).first()
                    if item:
                        match_method = "exact_title"

                # Strategy 4: Fuzzy title match (last resort)
                if not item and title and len(title) > 10:
                    # Try to find items with similar titles
                    similar_items = Item.query.filter(
                        Item.user_id == user_id,
                        Item.title.ilike(f"%{title[:20]}%")  # Match first 20 chars
                    ).all()

                    if len(similar_items) == 1:
                        # Only auto-match if there's exactly one similar item
                        item = similar_items[0]
                        match_method = "fuzzy_title"

                if item:
                    sale.item_id = item.id
                    if item.item_cost:
                        sale.item_cost = item.item_cost
                    sale.calculate_profit()
                    matched_count += 1
                    log_task(f"  ✓ Matched sale #{sale.id} to item #{item.id} (method: {match_method})")
                else:
                    still_unmatched += 1
                    log_task(f"  ✗ Could not match sale #{sale.id}: sku={sku}, title={title[:40]}")

                # Commit every 50 sales
                if (matched_count + still_unmatched) % 50 == 0:
                    db.session.commit()
                    log_task(f"Progress: processed {matched_count + still_unmatched}/{len(unlinked_sales)}")

            except Exception as e:
                log_task(f"  ERROR processing sale #{sale.id}: {str(e)}")
                continue

        # Final commit
        db.session.commit()

        log_task(f"=== Rematch completed ===")
        log_task(f"Matched: {matched_count}, Still unmatched: {still_unmatched}")

        return {
            'success': True,
            'total_processed': len(unlinked_sales),
            'matched': matched_count,
            'still_unmatched': still_unmatched
        }


@celery.task(bind=True, name='qventory.tasks.auto_relist_offers')
def auto_relist_offers(self):
    """
    Scheduled task to process auto-relist rules
    Runs periodically (every 15 minutes) to check for pending relists

    Handles both:
    - AUTO mode: Scheduled relists based on frequency
    - MANUAL mode: User-triggered relists with optional changes

    Returns:
        dict with execution results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.auto_relist_rule import AutoRelistRule, AutoRelistHistory
        from qventory.helpers.ebay_relist import execute_relist
        from datetime import datetime

        # Minimal logging to save server resources
        now = datetime.utcnow()

        # DEBUG: Check all rules first
        all_enabled_rules = AutoRelistRule.query.filter(AutoRelistRule.enabled == True).all()
        log_task(f"DEBUG: Found {len(all_enabled_rules)} enabled rules total")

        for rule in all_enabled_rules:
            log_task(f"  Rule {rule.id}: mode={rule.mode}, next_run_at={rule.next_run_at}, manual_trigger={getattr(rule, 'manual_trigger_requested', False)}")
            if rule.mode == 'auto' and rule.next_run_at:
                time_diff = (rule.next_run_at - now).total_seconds() / 60
                log_task(f"    Time until next run: {time_diff:.1f} minutes")

        auto_rules = AutoRelistRule.query.filter(
            AutoRelistRule.enabled == True,
            AutoRelistRule.mode == 'auto',
            AutoRelistRule.next_run_at <= now
        ).all()

        manual_rules = AutoRelistRule.query.filter(
            AutoRelistRule.enabled == True,
            AutoRelistRule.mode == 'manual',
            AutoRelistRule.manual_trigger_requested == True
        ).all()

        all_rules = auto_rules + manual_rules

        log_task(f"DEBUG: {len(auto_rules)} auto rules ready, {len(manual_rules)} manual rules triggered")

        if not all_rules:
            log_task("No rules to process - waiting for next_run_at or manual trigger")
            return {
                'success': True,
                'processed': 0,
                'succeeded': 0,
                'failed': 0,
                'skipped': 0
            }

        processed_count = 0
        succeeded_count = 0
        failed_count = 0
        skipped_count = 0

        for rule in all_rules:
            history = None  # Initialize history outside try block
            try:
                # Minimal logging for normal operations
                log_task(f"Processing rule {rule.id} ({rule.mode})")

                # Create history record
                history = AutoRelistHistory(
                    rule_id=rule.id,
                    user_id=rule.user_id,
                    mode=rule.mode,
                    started_at=datetime.utcnow(),
                    status='pending'
                )
                db.session.add(history)
                db.session.commit()

                # Capture old price if available
                if rule.current_price:
                    history.old_price = rule.current_price

                # SALE DETECTION: Check if item has been sold (auto mode only)
                if rule.mode == 'auto' and rule.listing_id:
                    from qventory.helpers.ebay_relist import check_item_sold_in_fulfillment

                    if check_item_sold_in_fulfillment(rule.user_id, rule.listing_id):
                        log_task(f"✓ Item SOLD - stopping auto-relist rule {rule.id}")

                        rule.enabled = False
                        rule.last_run_status = 'stopped_sold'
                        rule.last_run_at = datetime.utcnow()
                        rule.last_error_message = 'Rule stopped: item was sold'

                        history.status = 'skipped'
                        history.skip_reason = 'Item sold - found in fulfillment database'
                        history.mark_completed()

                        db.session.commit()
                        skipped_count += 1
                        processed_count += 1
                        continue

                # PRICE DECREASE: Calculate new price for auto mode
                new_price_from_decrease = None
                if rule.mode == 'auto' and rule.enable_price_decrease:
                    if not rule.current_price:
                        try:
                            # Detect if we should use Trading API (listing ID) or Inventory API (offer ID)
                            use_trading_api = (rule.offer_id and rule.offer_id.isdigit() and len(rule.offer_id) >= 10)

                            if use_trading_api:
                                # Use Trading API to get item price
                                from qventory.helpers.ebay_relist import get_item_details_trading_api
                                log_task(f"  Fetching current price via Trading API...")
                                price_resp = get_item_details_trading_api(rule.user_id, rule.offer_id)
                                if price_resp.get('success'):
                                    item_data = price_resp.get('item') or {}
                                    price_value = item_data.get('price')
                                    if price_value is not None:
                                        try:
                                            rule.current_price = float(price_value)
                                            log_task(f"  ✓ Fetched current price: ${rule.current_price}")
                                        except (TypeError, ValueError):
                                            pass
                            else:
                                # Use Inventory API to get offer price
                                from qventory.helpers.ebay_relist import get_offer_details
                                log_task(f"  Fetching current price via Inventory API...")
                                price_resp = get_offer_details(rule.user_id, rule.offer_id)
                                if price_resp.get('success'):
                                    offer_data = price_resp.get('offer') or {}
                                    price_value = (
                                        offer_data.get('pricingSummary', {})
                                        .get('price', {})
                                        .get('value')
                                    )
                                    if price_value is not None:
                                        try:
                                            rule.current_price = float(price_value)
                                            log_task(f"  ✓ Fetched current price: ${rule.current_price}")
                                        except (TypeError, ValueError):
                                            pass
                        except Exception as fetch_err:
                            log_task(f"  ⚠ Unable to refresh current price before decrease: {fetch_err}")

                    new_price_from_decrease = rule.calculate_new_price()
                    if new_price_from_decrease:
                        log_task(f"  Price decrease: ${rule.current_price} → ${new_price_from_decrease}")
                        history.new_price = new_price_from_decrease

                # Execute relist (with or without changes)
                # Check if manual mode has changes to apply
                has_changes = (rule.pending_changes and
                              isinstance(rule.pending_changes, dict) and
                              len(rule.pending_changes) > 0)
                apply_changes = rule.mode == 'manual' and has_changes

                log_task(f"  DEBUG: rule.mode = {rule.mode}")
                log_task(f"  DEBUG: rule.enable_price_decrease = {rule.enable_price_decrease}")
                log_task(f"  DEBUG: new_price_from_decrease = {new_price_from_decrease}")

                # For auto mode with price decrease, apply the price change
                if rule.mode == 'auto' and new_price_from_decrease:
                    apply_changes = True
                    # Create pending_changes for price decrease
                    if not rule.pending_changes:
                        rule.pending_changes = {}
                    rule.pending_changes['price'] = new_price_from_decrease
                    history.changes_applied = {'price': new_price_from_decrease}
                    log_task(f"  DEBUG: Set pending_changes['price'] = ${new_price_from_decrease}")
                    log_task(f"  DEBUG: apply_changes = {apply_changes}")
                    log_task(f"  DEBUG: rule.pending_changes = {rule.pending_changes}")

                    # CRITICAL: Commit pending_changes to database before passing rule to execute_relist
                    # SQLAlchemy JSON columns need explicit flag_modified to track changes
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(rule, 'pending_changes')
                    db.session.commit()
                    log_task(f"  DEBUG: Committed pending_changes to database")

                if apply_changes and rule.mode == 'manual':
                    history.changes_applied = rule.pending_changes.copy()
                    # Capture new price if changed
                    if 'price' in rule.pending_changes:
                        history.new_price = rule.pending_changes['price']

                # Execute relist
                log_task(f"  DEBUG: About to call execute_relist with apply_changes={apply_changes}")
                result = execute_relist(rule.user_id, rule, apply_changes=apply_changes)

                # Check result
                if 'skip_reason' in result:
                    # Skipped due to safety check
                    log_task(f"✗ Skipped: {result['skip_reason']}")

                    rule.mark_skipped(result['skip_reason'])

                    history.status = 'skipped'
                    history.skip_reason = result['skip_reason']
                    history.old_listing_id = result.get('old_listing_id')
                    history.mark_completed()

                    skipped_count += 1

                elif not result['success']:
                    # Failed
                    error_msg = result.get('error', 'Unknown error')
                    log_task(f"✗ Failed: {error_msg}")

                    rule.mark_error(error_msg)

                    history.status = 'error'
                    history.error_message = error_msg
                    history.old_listing_id = result.get('old_listing_id')
                    history.withdraw_response = result.get('details', {}).get('withdraw')
                    history.update_response = result.get('details', {}).get('update_offer') or result.get('details', {}).get('update_inventory')
                    history.publish_response = result.get('details', {}).get('publish')
                    history.mark_completed()

                    # Create error notification
                    from qventory.models.notification import Notification
                    item_title = rule.item_title or 'Item'
                    Notification.create_notification(
                        user_id=rule.user_id,
                        type='error',
                        title=f'Auto-relist failed',
                        message=f'{item_title[:50]}: {error_msg}',
                        link_url='/auto-relist',
                        link_text='View Details',
                        source='relist'
                    )

                    failed_count += 1

                else:
                    # Success!
                    new_listing_id = result['new_listing_id']
                    log_task(f"✓ Success! New listing ID: {new_listing_id}")

                    # Update current price if it was changed (do this BEFORE mark_success clears pending_changes)
                    if apply_changes and rule.pending_changes and 'price' in rule.pending_changes:
                        rule.current_price = rule.pending_changes['price']

                    # Fetch and update the new listing ID from eBay
                    from qventory.helpers.ebay_relist import get_new_listing_id_from_offer

                    updated_listing_id = get_new_listing_id_from_offer(rule.user_id, rule.offer_id)
                    if updated_listing_id:
                        new_listing_id = updated_listing_id
                        log_task(f"  Updated listing ID: {new_listing_id}")

                    rule.mark_success(new_listing_id)

                    history.status = 'success'
                    history.old_listing_id = result.get('old_listing_id')
                    history.new_listing_id = new_listing_id
                    history.withdraw_response = result.get('details', {}).get('withdraw')
                    history.update_response = result.get('details', {}).get('update_offer') or result.get('details', {}).get('update_inventory')
                    history.publish_response = result.get('details', {}).get('publish')
                    history.mark_completed()

                    # Create success notification
                    from qventory.models.notification import Notification
                    item_title = rule.item_title or 'Item'

                    # Check if this was the first relist
                    is_first_relist = rule.success_count == 1  # Just incremented in mark_success

                    if is_first_relist:
                        notification_title = 'First auto-relist completed! 🎉'
                        notification_message = f'{item_title[:50]} has been relisted successfully. New listing ID: {new_listing_id}. Next relist will run automatically based on your schedule.'
                    else:
                        notification_title = 'Auto-relist successful!'
                        notification_message = f'{item_title[:50]} was relisted with new listing ID {new_listing_id}'

                    Notification.create_notification(
                        user_id=rule.user_id,
                        type='success',
                        title=notification_title,
                        message=notification_message,
                        link_url='/auto-relist',
                        link_text='View Auto-Relist Dashboard',
                        source='relist'
                    )

                    succeeded_count += 1

                # Commit after each rule
                db.session.commit()
                processed_count += 1

            except Exception as e:
                log_task(f"✗ Exception during relist: {str(e)}")
                import traceback
                log_task(f"Traceback:\n{traceback.format_exc()}")

                rule.mark_error(f"Exception: {str(e)}")

                # Only update history if it was created
                if history:
                    history.status = 'error'
                    history.error_message = str(e)
                    history.mark_completed()

                db.session.commit()

                failed_count += 1
                processed_count += 1

        # Log only if there were failures
        if failed_count > 0:
            log_task(f"Auto-relist: {succeeded_count} succeeded, {failed_count} failed, {skipped_count} skipped")

        return {
            'success': True,
            'processed': processed_count,
            'succeeded': succeeded_count,
            'failed': failed_count,
            'skipped': skipped_count
        }


@celery.task(bind=True, name='qventory.tasks.process_webhook_event')
def process_webhook_event(self, event_id):
    """
    Process a webhook event asynchronously

    This task is triggered when a webhook event is received.
    It processes the event based on its topic/type.

    Args:
        event_id: WebhookEvent ID to process

    Returns:
        dict with processing results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.webhook import WebhookEvent, WebhookProcessingQueue

        log_task(f"=== Processing webhook event {event_id} ===")

        # Get event from database
        event = WebhookEvent.query.get(event_id)

        if not event:
            log_task(f"✗ Event {event_id} not found")
            return {'success': False, 'error': 'Event not found'}

        # Mark as processing
        event.mark_processing()

        # Get queue item
        queue_item = WebhookProcessingQueue.query.filter_by(event_id=event_id).first()
        if queue_item:
            queue_item.mark_processing(celery_task_id=self.request.id)

        try:
            log_task(f"Event topic: {event.topic}")
            log_task(f"Event for user: {event.user_id}")

            # Route to appropriate processor based on topic
            result = route_webhook_event(event)

            # Mark as completed
            event.mark_completed()
            if queue_item:
                queue_item.mark_completed()

            log_task(f"✓ Event processed successfully")

            return {
                'success': True,
                'event_id': event_id,
                'topic': event.topic,
                'result': result
            }

        except Exception as e:
            log_task(f"✗ Error processing event: {str(e)}")

            # Mark as failed
            error_details = {
                'error': str(e),
                'task_id': self.request.id
            }
            event.mark_failed(str(e), error_details)

            if queue_item:
                queue_item.mark_failed_with_retry()

            return {
                'success': False,
                'event_id': event_id,
                'error': str(e)
            }


def route_webhook_event(event):
    """
    Route webhook event to appropriate processor

    Args:
        event: WebhookEvent object

    Returns:
        dict with processing result
    """
    topic = event.topic
    payload = event.payload

    log_task(f"Routing event with topic: {topic}")

    # Map topics to processors
    # For Sprint 1, we just log the events
    # Sprint 3 and 4 will implement actual processors

    if topic == 'ITEM_SOLD':
        return process_item_sold_event(event)
    elif topic == 'ITEM_ENDED':
        return process_item_ended_event(event)
    elif topic == 'ITEM_OUT_OF_STOCK':
        return process_item_out_of_stock_event(event)
    elif topic == 'FULFILLMENT_ORDER_SHIPPED':
        return process_order_shipped_event(event)
    elif topic == 'FULFILLMENT_ORDER_DELIVERED':
        return process_order_delivered_event(event)
    else:
        log_task(f"⚠️  No processor for topic: {topic}")
        return {'status': 'no_processor', 'message': f'No processor implemented for {topic}'}


# === Event Processors (Sprint 3 & 4) ===

def process_item_sold_event(event):
    """
    Process ITEM_SOLD event - Create sale record and update inventory

    This processor:
    1. Extracts sale data from eBay webhook payload
    2. Finds the matching item in inventory
    3. Creates a Sale record
    4. Calculates profit automatically
    5. Notifies the user
    """
    from qventory.models.sale import Sale
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task(f"Processing ITEM_SOLD event")

    try:
        payload = event.payload
        notification = payload.get('notification', {})

        # Extract sale data from eBay notification
        listing_id = notification.get('listingId')
        sold_price = float(notification.get('price', {}).get('value', 0))
        currency = notification.get('price', {}).get('currency', 'USD')
        quantity_sold = int(notification.get('quantity', 1))
        buyer_username = notification.get('buyerUsername', '')
        transaction_id = notification.get('transactionId', '')
        order_id = notification.get('orderId', '')

        log_task(f"  Listing ID: {listing_id}")
        log_task(f"  Price: {sold_price} {currency}")
        log_task(f"  Quantity: {quantity_sold}")
        log_task(f"  Buyer: {buyer_username}")

        if not listing_id:
            log_task(f"  ⚠️  No listing ID in notification")
            return {'status': 'error', 'message': 'Missing listing ID'}

        # Find the item in inventory
        item = None
        if event.user_id:
            item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_listing_id=str(listing_id)
            ).first()

            if item:
                log_task(f"  ✓ Found item: {item.title}")
            else:
                log_task(f"  ⚠️  Item not found (listing_id: {listing_id})")

        # Calculate eBay fees (approximate)
        marketplace_fee = sold_price * 0.1325  # ~13.25% eBay final value fee
        payment_fee = sold_price * 0.029 + 0.30  # Payment processing

        # Check for duplicates
        existing_sale = Sale.query.filter_by(
            user_id=event.user_id,
            marketplace='ebay',
            marketplace_order_id=order_id or transaction_id
        ).first()

        if existing_sale:
            log_task(f"  ⚠️  Duplicate sale (ID: {existing_sale.id})")
            return {'status': 'duplicate', 'sale_id': existing_sale.id}

        # Create new sale record
        new_sale = Sale(
            user_id=event.user_id,
            item_id=item.id if item else None,
            marketplace='ebay',
            marketplace_order_id=order_id or transaction_id,
            item_title=item.title if item else f'eBay Item {listing_id}',
            item_sku=item.sku if item else None,
            sold_price=sold_price,
            item_cost=item.item_cost if item else None,
            marketplace_fee=marketplace_fee,
            payment_processing_fee=payment_fee,
            sold_at=datetime.utcnow(),
            status='paid',
            ebay_transaction_id=transaction_id,
            ebay_buyer_username=buyer_username,
            buyer_username=buyer_username
        )

        new_sale.calculate_profit()
        db.session.add(new_sale)
        db.session.commit()

        log_task(f"  ✓ Sale created (ID: {new_sale.id})")
        log_task(f"  Net profit: ${new_sale.net_profit:.2f}" if new_sale.net_profit else "  Net profit: N/A")

        # Notify user
        from qventory.models.notification import Notification
        profit_text = f"${new_sale.net_profit:.2f} profit" if new_sale.net_profit else "profit unknown"
        Notification.create_notification(
            user_id=event.user_id,
            type='success',
            title='Item sold!',
            message=f'{new_sale.item_title[:50]} sold for ${sold_price:.2f} ({profit_text})',
            link_url='/fulfillment',
            link_text='View Order',
            source='webhook'
        )

        return {
            'status': 'success',
            'sale_id': new_sale.id,
            'sold_price': sold_price,
            'net_profit': new_sale.net_profit
        }

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        import traceback
        log_task(f"  {traceback.format_exc()}")
        return {'status': 'error', 'message': str(e)}


def process_item_ended_event(event):
    """
    Process ITEM_ENDED event - Update item when listing ends
    """
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task(f"Processing ITEM_ENDED event")

    try:
        payload = event.payload
        notification = payload.get('notification', {})

        listing_id = notification.get('listingId')
        end_reason = notification.get('reason', 'ENDED')

        log_task(f"  Listing ID: {listing_id}")
        log_task(f"  Reason: {end_reason}")

        if not listing_id or not event.user_id:
            return {'status': 'error', 'message': 'Missing data'}

        item = Item.query.filter_by(
            user_id=event.user_id,
            ebay_listing_id=str(listing_id)
        ).first()

        if not item:
            log_task(f"  ⚠️  Item not found")
            return {'status': 'not_found'}

        log_task(f"  ✓ Found: {item.title}")

        # Add note about listing end
        end_note = f"\n[{datetime.utcnow().strftime('%Y-%m-%d')}] Listing ended on eBay ({end_reason})"
        if item.notes:
            item.notes += end_note
        else:
            item.notes = end_note.strip()

        item.updated_at = datetime.utcnow()
        db.session.commit()

        log_task(f"  ✓ Item updated")

        return {'status': 'success', 'item_id': item.id}

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def process_item_out_of_stock_event(event):
    """
    Process ITEM_OUT_OF_STOCK event - Mark item as out of stock
    """
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task(f"Processing ITEM_OUT_OF_STOCK event")

    try:
        payload = event.payload
        notification = payload.get('notification', {})

        listing_id = notification.get('listingId')
        sku = notification.get('sku')

        log_task(f"  Listing ID: {listing_id}")

        if not event.user_id:
            return {'status': 'error', 'message': 'Missing user ID'}

        # Find item by listing ID or SKU
        item = None
        if listing_id:
            item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_listing_id=str(listing_id)
            ).first()

        if not item and sku:
            item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_sku=sku
            ).first()

        if not item:
            log_task(f"  ⚠️  Item not found")
            return {'status': 'not_found'}

        log_task(f"  ✓ Found: {item.title}")

        # Add out of stock note
        oos_note = f"\n[{datetime.utcnow().strftime('%Y-%m-%d')}] Out of stock on eBay"
        if item.notes:
            item.notes += oos_note
        else:
            item.notes = oos_note.strip()

        item.updated_at = datetime.utcnow()
        db.session.commit()

        log_task(f"  ✓ Marked out of stock")

        # Notify user
        from qventory.models.notification import Notification
        Notification.create_notification(
            user_id=event.user_id,
            type='warning',
            title='Item out of stock',
            message=f'{item.title[:50]} is now out of stock on eBay',
            link_url=f'/item/{item.id}/edit',
            link_text='View Item',
            source='webhook'
        )

        return {'status': 'success', 'item_id': item.id}

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def process_order_shipped_event(event):
    """Process FULFILLMENT_ORDER_SHIPPED event - Sprint 4"""
    log_task(f"  TODO: Implement ORDER_SHIPPED processor")
    return {'status': 'placeholder', 'message': 'ORDER_SHIPPED processor not yet implemented'}


def process_order_delivered_event(event):
    """Process FULFILLMENT_ORDER_DELIVERED event - Sprint 4"""
    log_task(f"  TODO: Implement ORDER_DELIVERED processor")
    return {'status': 'placeholder', 'message': 'ORDER_DELIVERED processor not yet implemented'}


@celery.task(bind=True, name='qventory.tasks.renew_expiring_webhooks')
def renew_expiring_webhooks(self):
    """
    Scheduled task to auto-renew webhook subscriptions that are expiring soon

    eBay webhook subscriptions expire after 7 days and must be renewed.
    This task runs daily to check for subscriptions expiring within 2 days
    and renews them automatically.

    Returns:
        dict with renewal results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.webhook import WebhookSubscription
        from qventory.helpers.ebay_webhooks import renew_webhook_subscription
        from datetime import datetime, timedelta

        log_task("=== Starting webhook renewal check ===")

        # Find subscriptions that need renewal (expiring within 2 days)
        threshold = datetime.utcnow() + timedelta(days=2)

        expiring_subs = WebhookSubscription.query.filter(
            WebhookSubscription.status == 'ENABLED',
            WebhookSubscription.expires_at <= threshold
        ).all()

        log_task(f"Found {len(expiring_subs)} subscriptions that need renewal")

        if not expiring_subs:
            log_task("No subscriptions need renewal at this time")
            return {
                'success': True,
                'total_checked': 0,
                'renewed': 0,
                'failed': 0
            }

        renewed_count = 0
        failed_count = 0

        for sub in expiring_subs:
            try:
                log_task(f"Renewing subscription {sub.id} for user {sub.user_id}")
                log_task(f"  Topic: {sub.topic}")
                log_task(f"  Expires at: {sub.expires_at}")
                log_task(f"  Subscription ID: {sub.subscription_id}")

                # Call eBay API to renew the subscription
                result = renew_webhook_subscription(
                    user_id=sub.user_id,
                    subscription_id=sub.subscription_id
                )

                if result['success']:
                    # Update expiration date in database
                    sub.expires_at = result['expires_at']
                    sub.error_count = 0  # Reset error count on success
                    sub.last_error_message = None
                    db.session.commit()

                    renewed_count += 1
                    log_task(f"✓ Renewed successfully. New expiration: {result['expires_at']}")

                else:
                    # Renewal failed
                    error_msg = result.get('error', 'Unknown error')
                    log_task(f"✗ Renewal failed: {error_msg}")

                    # Update error tracking
                    sub.error_count = (sub.error_count or 0) + 1
                    sub.last_error_message = error_msg
                    sub.last_error_at = datetime.utcnow()

                    # If renewal fails 3 times, disable the subscription
                    if sub.error_count >= 3:
                        log_task(f"⚠️  Disabling subscription after {sub.error_count} failures")
                        sub.status = 'DISABLED'

                        # Create admin notification
                        from qventory.models.notification import Notification
                        Notification.create_notification(
                            user_id=sub.user_id,
                            type='error',
                            title='Webhook subscription disabled',
                            message=f'Subscription for {sub.topic} was disabled after multiple renewal failures. Please reconnect your eBay account.',
                            link_url='/settings',
                            link_text='Go to Settings',
                            source='webhook'
                        )

                    db.session.commit()
                    failed_count += 1

            except Exception as e:
                log_task(f"✗ Exception renewing subscription {sub.id}: {str(e)}")
                import traceback
                log_task(f"Traceback: {traceback.format_exc()}")

                # Update error tracking
                sub.error_count = (sub.error_count or 0) + 1
                sub.last_error_message = f"Exception: {str(e)}"
                sub.last_error_at = datetime.utcnow()

                # Disable after 3 failures
                if sub.error_count >= 3:
                    sub.status = 'DISABLED'

                db.session.commit()
                failed_count += 1

        log_task(f"=== Renewal check completed ===")
        log_task(f"Total checked: {len(expiring_subs)}")
        log_task(f"Renewed: {renewed_count}")
        log_task(f"Failed: {failed_count}")

        return {
            'success': True,
            'total_checked': len(expiring_subs),
            'renewed': renewed_count,
            'failed': failed_count
        }


@celery.task(bind=True, name='qventory.tasks.process_platform_notification')
def process_platform_notification(self, event_id):
    """
    Process eBay Platform Notification (SOAP/XML from Trading API)

    Handles real-time sync for:
    - AddItem: New listing created → Import to Qventory
    - ReviseItem: Listing updated → Update in Qventory
    - RelistItem: Listing relisted → Update in Qventory

    Args:
        event_id: WebhookEvent ID to process
    """
    app = create_app()

    with app.app_context():
        from qventory.models.webhook import WebhookEvent
        from qventory.extensions import db

        # Get event from database
        event = WebhookEvent.query.get(event_id)

        if not event:
            log_task(f"✗ Event {event_id} not found")
            return {'status': 'error', 'message': 'Event not found'}

        log_task(f"Processing Platform Notification: {event.topic}")

        try:
            # Mark as processing
            event.status = 'processing'
            event.processed_at = datetime.utcnow()
            db.session.commit()

            # Get notification type
            payload = event.payload
            notification_type = payload.get('notification_type')

            # Route to appropriate processor
            if notification_type == 'AddItem':
                result = process_add_item_notification(event)
            elif notification_type == 'ReviseItem':
                result = process_revise_item_notification(event)
            elif notification_type == 'RelistItem':
                result = process_relist_item_notification(event)
            else:
                log_task(f"⚠️  Unknown notification type: {notification_type}")
                result = {'status': 'skipped', 'message': f'Unknown type: {notification_type}'}

            # Update event status
            if result.get('status') == 'success':
                event.status = 'completed'
                event.result = result
            else:
                event.status = 'failed'
                event.error_message = result.get('message', 'Unknown error')

            db.session.commit()

            log_task(f"✓ Platform notification processed: {result.get('status')}")
            return result

        except Exception as e:
            log_task(f"✗ Error processing Platform notification: {str(e)}")
            import traceback
            log_task(f"Traceback: {traceback.format_exc()}")

            # Mark as failed
            event.status = 'failed'
            event.error_message = str(e)
            db.session.commit()

            return {'status': 'error', 'message': str(e)}


def process_add_item_notification(event):
    """
    Process AddItem notification - Import new listing to Qventory

    This is the CRITICAL function for real-time new listing sync.
    When user creates item on eBay, this imports it to Qventory in seconds.

    Args:
        event: WebhookEvent with AddItem data

    Returns:
        dict: Processing result
    """
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task("Processing AddItem notification")

    try:
        payload = event.payload
        data = payload.get('data', {})

        # Extract item details
        ebay_listing_id = payload.get('item_id')
        title = data.get('title', '')
        ebay_sku = data.get('sku', '')
        listing_type = data.get('listing_type', '')
        quantity = data.get('quantity', '1')

        # Extract pricing
        start_price = data.get('start_price', '')
        buy_it_now_price = data.get('buy_it_now_price', '')

        # Determine listing price (prefer Buy It Now, fallback to start price)
        listing_price = None
        if buy_it_now_price:
            try:
                listing_price = float(buy_it_now_price)
            except (ValueError, TypeError):
                pass

        if not listing_price and start_price:
            try:
                listing_price = float(start_price)
            except (ValueError, TypeError):
                pass

        log_task(f"  Item ID: {ebay_listing_id}")
        log_task(f"  Title: {title}")
        log_task(f"  SKU: {ebay_sku or 'N/A'}")
        log_task(f"  Price: ${listing_price}" if listing_price else "  Price: N/A")

        # Check if item already exists
        existing_item = None
        if event.user_id:
            existing_item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_listing_id=ebay_listing_id
            ).first()

        if existing_item:
            log_task(f"  ⚠️  Item already exists: {existing_item.id}")
            return {
                'status': 'duplicate',
                'item_id': existing_item.id,
                'message': 'Item already exists in database'
            }

        # Generate SKU if not provided
        if not ebay_sku:
            from qventory.helpers import generate_sku
            ebay_sku = generate_sku()

        # Create new item in Qventory
        new_item = Item(
            user_id=event.user_id,
            title=title[:500] if title else 'eBay Item',  # Truncate to fit DB
            sku=ebay_sku[:50] if ebay_sku else None,
            ebay_listing_id=ebay_listing_id,
            ebay_sku=ebay_sku[:100] if ebay_sku else None,
            listing_link=data.get('view_url', ''),
            listing_price=listing_price,
            synced_from_ebay=True,
            last_ebay_sync=datetime.utcnow(),
            notes=f"Auto-imported from eBay on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} via Platform Notifications"
        )

        db.session.add(new_item)
        db.session.commit()

        log_task(f"  ✓ Created item {new_item.id}")

        # Send notification to user
        from qventory.models.notification import Notification
        Notification.create_notification(
            user_id=event.user_id,
            type='success',
            title='New eBay listing imported!',
            message=f'{title[:50]} was automatically imported from eBay',
            link_url=f'/item/{new_item.id}',
            link_text='View Item',
            source='webhook'
        )

        return {
            'status': 'success',
            'item_id': new_item.id,
            'title': title,
            'ebay_listing_id': ebay_listing_id,
            'message': 'Item imported successfully'
        }

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        import traceback
        log_task(f"Traceback: {traceback.format_exc()}")
        return {'status': 'error', 'message': str(e)}


def process_revise_item_notification(event):
    """
    Process ReviseItem notification - Update listing in Qventory

    Args:
        event: WebhookEvent with ReviseItem data

    Returns:
        dict: Processing result
    """
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task("Processing ReviseItem notification")

    try:
        payload = event.payload
        data = payload.get('data', {})

        ebay_listing_id = payload.get('item_id')

        # Find item in database
        item = None
        if event.user_id:
            item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_listing_id=ebay_listing_id
            ).first()

        if not item:
            log_task(f"  ⚠️  Item not found: {ebay_listing_id}")
            return {
                'status': 'not_found',
                'message': f'Item {ebay_listing_id} not found in database'
            }

        # Update item details
        updated_fields = []

        title = data.get('title')
        if title and title != item.title:
            item.title = title[:500]
            updated_fields.append('title')

        # Update pricing
        buy_it_now_price = data.get('buy_it_now_price')
        start_price = data.get('start_price')

        new_price = None
        if buy_it_now_price:
            try:
                new_price = float(buy_it_now_price)
            except (ValueError, TypeError):
                pass

        if not new_price and start_price:
            try:
                new_price = float(start_price)
            except (ValueError, TypeError):
                pass

        if new_price and new_price != item.listing_price:
            item.listing_price = new_price
            updated_fields.append('price')

        # Update sync timestamp
        item.last_ebay_sync = datetime.utcnow()

        # Add note about update
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        update_note = f"\\n[{timestamp}] Updated from eBay: {', '.join(updated_fields) if updated_fields else 'metadata'}"
        item.notes = (item.notes or '') + update_note

        db.session.commit()

        log_task(f"  ✓ Updated item {item.id}: {', '.join(updated_fields) if updated_fields else 'metadata'}")

        return {
            'status': 'success',
            'item_id': item.id,
            'updated_fields': updated_fields,
            'message': 'Item updated successfully'
        }

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def process_relist_item_notification(event):
    """
    Process RelistItem notification - Item was relisted

    Args:
        event: WebhookEvent with RelistItem data

    Returns:
        dict: Processing result
    """
    from qventory.models.item import Item
    from qventory.extensions import db

    log_task("Processing RelistItem notification")

    try:
        payload = event.payload
        ebay_listing_id = payload.get('item_id')

        # Find item in database
        item = None
        if event.user_id:
            item = Item.query.filter_by(
                user_id=event.user_id,
                ebay_listing_id=ebay_listing_id
            ).first()

        if not item:
            log_task(f"  ⚠️  Item not found: {ebay_listing_id}")
            return {
                'status': 'not_found',
                'message': f'Item {ebay_listing_id} not found'
            }

        # Add relist note
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        relist_note = f"\\n[{timestamp}] Listing relisted on eBay"
        item.notes = (item.notes or '') + relist_note
        item.last_ebay_sync = datetime.utcnow()

        db.session.commit()

        log_task(f"  ✓ Updated item {item.id} with relist note")

        return {
            'status': 'success',
            'item_id': item.id,
            'message': 'Relist noted'
        }

    except Exception as e:
        log_task(f"  ✗ Error: {str(e)}")
        return {'status': 'error', 'message': str(e)}


@celery.task(bind=True, name='qventory.tasks.poll_ebay_new_listings')
def poll_ebay_new_listings(self):
    """
    Poll eBay GetSellerEvents for new listings and import them automatically

    This task runs every 60 seconds and checks for new listings created
    in the last 5 minutes. It's an alternative to Platform Notifications
    that works with OAuth 2.0.

    Smart polling: Only checks users who are "active" to reduce API load.

    Returns:
        dict: Summary of polling results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.user import User
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.item import Item
        from datetime import datetime, timedelta
        import requests

        log_task("=== Polling eBay for new listings ===")

        # Get all users with active eBay credentials
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No users with eBay connected")
            return {
                'success': True,
                'users_checked': 0,
                'new_listings': 0,
                'errors': 0
            }

        # Smart polling: Filter to only "active" users
        active_credentials = []
        for cred in credentials:
            # Check if user has created/updated items in last 30 days
            # Or has logged in recently
            user = User.query.get(cred.user_id)
            if user and should_poll_user(user, cred):
                active_credentials.append(cred)

        log_task(f"Found {len(active_credentials)} active users to check (out of {len(credentials)} total)")

        total_new = 0
        total_errors = 0

        for cred in active_credentials:
            try:
                result = poll_user_listings(cred)
                total_new += result.get('new_listings', 0)

                if result.get('new_listings', 0) > 0:
                    log_task(f"  User {cred.user_id}: {result['new_listings']} new listings imported")

            except Exception as e:
                log_task(f"  ✗ Error polling user {cred.user_id}: {str(e)}")
                total_errors += 1

        log_task(f"=== Polling complete: {total_new} new listings, {total_errors} errors ===")

        return {
            'success': True,
            'users_checked': len(active_credentials),
            'new_listings': total_new,
            'errors': total_errors
        }


def should_poll_user(user, credential):
    """
    Determine if we should poll this user's eBay account

    Smart polling logic:
    - Always poll if last login < 24 hours
    - Always poll if items created/updated < 7 days
    - Poll every 10 minutes if last activity < 30 days
    - Poll every hour if last activity > 30 days

    Args:
        user: User object
        credential: MarketplaceCredential object

    Returns:
        bool: True if should poll now
    """
    from datetime import datetime, timedelta

    now = datetime.utcnow()

    # Always poll if logged in recently (active users)
    if user.last_login and (now - user.last_login) < timedelta(hours=24):
        return True

    # Check last polling time (stored in credential for efficiency)
    last_poll = getattr(credential, 'last_poll_at', None)

    # First time polling - always check
    if not last_poll:
        return True

    # Check if user has recent item activity
    from qventory.models.item import Item
    recent_item = Item.query.filter_by(user_id=user.id).filter(
        Item.created_at > (now - timedelta(days=7))
    ).first()

    if recent_item:
        # Active seller - poll every 60 seconds (this task's frequency)
        return True

    # Check if user has activity in last 30 days
    activity_30d = Item.query.filter_by(user_id=user.id).filter(
        Item.created_at > (now - timedelta(days=30))
    ).first()

    if activity_30d:
        # Somewhat active - poll every 10 minutes
        return (now - last_poll) >= timedelta(minutes=10)

    # Inactive user - poll every hour
    return (now - last_poll) >= timedelta(hours=1)


def refresh_ebay_token(credential):
    """
    Refresh eBay OAuth token if expired

    Args:
        credential: MarketplaceCredential object

    Returns:
        dict: {'success': bool, 'error': str (if failed)}
    """
    try:
        from qventory.routes.ebay_auth import refresh_access_token
        from datetime import datetime

        # Use the existing refresh function (decrypt refresh_token first)
        token_data = refresh_access_token(credential.get_refresh_token())

        # Update credential with new tokens (setters will encrypt)
        credential.set_access_token(token_data['access_token'])
        if 'refresh_token' in token_data:
            credential.set_refresh_token(token_data['refresh_token'])
        credential.created_at = datetime.utcnow()  # Reset token age
        db.session.commit()

        return {'success': True}

    except Exception as e:
        log_task(f"    Token refresh exception: {str(e)}")
        return {'success': False, 'error': str(e)}


def poll_user_listings(credential):
    """
    Poll eBay for ALL active listings and import missing ones
    
    This ensures we never miss listings, regardless of when they were created.
    
    Args:
        credential: MarketplaceCredential object
    
    Returns:
        dict: {'new_listings': int, 'errors': []}
    """
    from datetime import datetime
    from qventory.models.item import Item
    from qventory.helpers import generate_sku
    import os
    import requests
    
    user_id = credential.user_id

    # Check if token needs refresh (eBay tokens expire after 2 hours)
    # We'll refresh if token is older than 1.5 hours to be safe
    from datetime import timedelta
    token_age = datetime.utcnow() - credential.created_at
    if token_age > timedelta(hours=1, minutes=30):
        log_task(f"    Token is {token_age.total_seconds()/3600:.1f}h old, refreshing...")
        refresh_result = refresh_ebay_token(credential)
        if not refresh_result['success']:
            log_task(f"    ✗ Token refresh failed: {refresh_result.get('error', 'Unknown error')}")
            return {'new_listings': 0, 'errors': ['Token refresh failed']}
        log_task(f"    ✓ Token refreshed successfully")

    access_token = credential.get_access_token()  # Decrypt token

    # Update last poll time
    credential.last_poll_at = datetime.utcnow()
    db.session.commit()
    
    # eBay Trading API endpoint
    is_sandbox = os.environ.get('EBAY_SANDBOX', 'false').lower() == 'true'
    api_url = (
        'https://api.sandbox.ebay.com/ws/api.dll'
        if is_sandbox else
        'https://api.ebay.com/ws/api.dll'
    )
    
    # Build GetSellerList XML request (gets ALL active listings)
    ebay_app_id = os.environ.get('EBAY_CLIENT_ID')
    ebay_dev_id = os.environ.get('EBAY_DEV_ID')
    ebay_cert_id = os.environ.get('EBAY_CERT_ID')

    # eBay requires a time range - use last 120 days to catch all active listings
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=120)

    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <StartTimeFrom>{start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</StartTimeFrom>
  <StartTimeTo>{end_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</StartTimeTo>
  <IncludeWatchCount>true</IncludeWatchCount>
  <DetailLevel>ReturnAll</DetailLevel>
  <GranularityLevel>Fine</GranularityLevel>
  <Pagination>
    <EntriesPerPage>200</EntriesPerPage>
    <PageNumber>1</PageNumber>
  </Pagination>
</GetSellerListRequest>'''
    
    headers = {
        'X-EBAY-API-COMPATIBILITY-LEVEL': '1193',
        'X-EBAY-API-DEV-NAME': ebay_dev_id,
        'X-EBAY-API-APP-NAME': ebay_app_id,
        'X-EBAY-API-CERT-NAME': ebay_cert_id,
        'X-EBAY-API-CALL-NAME': 'GetSellerList',
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-IAF-TOKEN': access_token,
        'Content-Type': 'text/xml'
    }
    
    try:
        response = requests.post(api_url, data=xml_request, headers=headers, timeout=30)
        
        if response.status_code != 200:
            log_task(f"    GetSellerList failed: {response.status_code}")
            return {'new_listings': 0, 'errors': [f'HTTP {response.status_code}']}
        
        # Parse XML response
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.text)
        
        # Check for success
        ack = root.find('.//{urn:ebay:apis:eBLBaseComponents}Ack')
        if ack is None or ack.text not in ['Success', 'Warning']:
            errors = root.findall('.//{urn:ebay:apis:eBLBaseComponents}Errors')
            error_msgs = [e.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage').text
                         for e in errors if e.find('.//{urn:ebay:apis:eBLBaseComponents}LongMessage') is not None]
            log_task(f"    GetSellerList error: {'; '.join(error_msgs)}")
            return {'new_listings': 0, 'errors': error_msgs}
        
        # Get existing listing IDs from database
        existing_listing_ids = set()
        existing_items = Item.query.filter_by(user_id=user_id).filter(
            Item.ebay_listing_id.isnot(None)
        ).all()
        for item in existing_items:
            existing_listing_ids.add(item.ebay_listing_id)
        
        log_task(f"    User has {len(existing_listing_ids)} existing eBay listings in database")
        
        # Extract items from ItemArray
        items = root.findall('.//{urn:ebay:apis:eBLBaseComponents}ItemArray/{urn:ebay:apis:eBLBaseComponents}Item')

        log_task(f"    Found {len(items)} active listings on eBay")

        # DEBUG: Log all listing IDs from eBay
        ebay_listing_ids = []
        for item_elem in items:
            item_id = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ItemID')
            if item_id is not None and item_id.text:
                ebay_listing_ids.append(item_id.text)
        log_task(f"    eBay listing IDs: {', '.join(ebay_listing_ids)}")
        log_task(f"    Existing listing IDs in DB: {', '.join(existing_listing_ids)}")

        new_listings = 0
        active_count = 0
        skipped_inactive = 0
        skipped_existing = 0

        for item_elem in items:
            item_id = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ItemID')
            title = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}Title')

            if item_id is None or title is None:
                continue

            item_id_text = item_id.text
            title_text = title.text

            # CRITICAL: Only import ACTIVE listings
            selling_status = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}SellingStatus/{urn:ebay:apis:eBLBaseComponents}ListingStatus')
            if selling_status is None or selling_status.text != 'Active':
                skipped_inactive += 1
                continue  # Skip ended, sold, completed listings

            active_count += 1

            # Skip if already in database
            if item_id_text in existing_listing_ids:
                skipped_existing += 1
                continue
            
            # Extract price
            price_elem = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}StartPrice')
            bin_price_elem = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}BuyItNowPrice')
            
            price = None
            if bin_price_elem is not None and bin_price_elem.text:
                try:
                    price = float(bin_price_elem.text)
                except:
                    pass
            
            if not price and price_elem is not None and price_elem.text:
                try:
                    price = float(price_elem.text)
                except:
                    pass
            
            # Extract SKU
            sku_elem = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}SKU')
            sku = sku_elem.text if sku_elem is not None and sku_elem.text else generate_sku()
            
            # Extract listing URL
            view_url_elem = item_elem.find('.//{urn:ebay:apis:eBLBaseComponents}ListingDetails/{urn:ebay:apis:eBLBaseComponents}ViewItemURL')
            view_url = view_url_elem.text if view_url_elem is not None else f'https://www.ebay.com/itm/{item_id_text}'
            
            # Create new item
            new_item = Item(
                user_id=user_id,
                title=title_text[:500] if title_text else 'eBay Item',
                sku=sku[:50] if sku else generate_sku(),
                ebay_listing_id=item_id_text,
                ebay_sku=sku[:100] if sku else None,
                listing_link=view_url,
                item_price=price,
                synced_from_ebay=True,
                last_ebay_sync=datetime.utcnow(),
                notes=f"Auto-imported from eBay on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} via polling"
            )
            
            db.session.add(new_item)
            new_listings += 1
            
            log_task(f"    ✓ New listing: {title_text[:50]}")

        log_task(f"    Summary: {active_count} active, {skipped_inactive} inactive, {skipped_existing} already in DB, {new_listings} imported")

        if new_listings > 0:
            db.session.commit()
            
            # Send notification to user
            from qventory.models.notification import Notification
            if new_listings == 1:
                Notification.create_notification(
                    user_id=user_id,
                    type='success',
                    title='New eBay listing imported!',
                    message=f'{title_text[:50]} was automatically imported',
                    link_url='/inventory',
                    link_text='View Inventory',
                    source='ebay_sync'
                )
            else:
                Notification.create_notification(
                    user_id=user_id,
                    type='success',
                    title=f'{new_listings} eBay listings imported!',
                    message=f'{new_listings} new listings were automatically imported from eBay',
                    link_url='/inventory',
                    link_text='View Inventory',
                    source='ebay_sync'
                )
        
        return {'new_listings': new_listings, 'errors': []}
    
    except Exception as e:
        log_task(f"    ✗ Exception: {str(e)}")
        import traceback
        log_task(f"    Traceback: {traceback.format_exc()}")
        return {'new_listings': 0, 'errors': [str(e)]}
