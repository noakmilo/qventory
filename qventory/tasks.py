"""
Celery Background Tasks for Qventory
"""
import hashlib
import sys
import time
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from qventory.celery_app import celery
from qventory.extensions import db
from qventory import create_app

def log_task(msg):
    """Helper function for task logging"""
    print(f"[CELERY_TASK] {msg}", file=sys.stderr, flush=True)


def _parse_ebay_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _build_external_id(prefix, parts):
    payload = "|".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"[:64]


@celery.task(bind=True, name='qventory.tasks.relist_item_sell_similar')
def relist_item_sell_similar(self, user_id, item_id, title=None, price=None):
    app = create_app()

    with app.app_context():
        from qventory.models.item import Item
        from qventory.helpers.ebay_relist import end_item_trading_api, relist_item_trading_api

        log_task("=== EndItem + RelistItem task ===")
        log_task(f"  user_id={user_id} item_id={item_id}")

        item = Item.query.filter_by(id=item_id, user_id=user_id).first()
        if not item:
            log_task("  ✗ Item not found")
            return {'success': False, 'error': 'Item not found'}

        if not item.ebay_listing_id:
            log_task("  ✗ Missing eBay listing ID")
            return {'success': False, 'error': 'Missing eBay listing ID'}

        listing_id = item.ebay_listing_id
        changes = {}
        if title:
            changes['title'] = title
        if price is not None:
            changes['price'] = price

        log_task(f"  Step 1/2: EndItem {listing_id}")
        end_result = end_item_trading_api(user_id, listing_id)
        log_task(f"  EndItem result: {end_result}")
        if not end_result.get('success'):
            return {'success': False, 'error': end_result.get('error') or 'Failed to end listing'}

        log_task(f"  Step 2/2: RelistItem for {listing_id}")
        relist_result = relist_item_trading_api(user_id, listing_id, changes=changes)
        log_task(f"  RelistItem result: {relist_result}")
        if not relist_result.get('success'):
            return {'success': False, 'error': relist_result.get('error') or 'Relist failed'}

        new_listing_id = relist_result.get('listing_id')
        if not new_listing_id:
            return {'success': False, 'error': 'Missing new listing ID'}

        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        relist_note = f"\n[{timestamp}] Relist pending: {new_listing_id} (from {listing_id})"
        item.notes = (item.notes or '') + relist_note
        db.session.commit()

        log_task(f"  ✓ Relist queued for polling transfer: new_listing_id={new_listing_id}")

        # Record relist history for manual relist
        try:
            from qventory.models.auto_relist_rule import AutoRelistHistory
            history = AutoRelistHistory(
                rule_id=None,
                user_id=user_id,
                item_id=item.id,
                sku=item.sku,
                mode="manual",
                started_at=datetime.utcnow(),
                status="success",
                old_listing_id=listing_id,
                new_listing_id=new_listing_id,
                old_price=item.item_price,
                new_price=price if price is not None else item.item_price,
                old_title=item.title,
                new_title=title if title else item.title,
                changes_applied=changes or None
            )
            history.mark_completed()
            db.session.add(history)
            db.session.commit()
        except Exception as e:
            log_task(f"  ⚠ Failed to write relist history: {e}")

        return {
            'success': True,
            'new_listing_id': new_listing_id,
            'old_listing_id': listing_id
        }


@celery.task(bind=True, name='qventory.tasks.refresh_user_analytics')
def refresh_user_analytics(self, user_id, days_back=90, force=False):
    app = create_app()

    with app.app_context():
        from qventory.models.system_setting import SystemSetting

        log_task("=== Analytics refresh task ===")
        log_task(f"  user_id={user_id} days_back={days_back} force={force}")

        now_ts = int(datetime.utcnow().timestamp())
        throttle_key = f"analytics_refresh_last_{user_id}"

        if not force:
            last_ts = SystemSetting.get_int(throttle_key)
            if last_ts and now_ts - last_ts < 600:
                log_task(f"  Skipping analytics refresh (last run {now_ts - last_ts}s ago)")
                return {'success': True, 'skipped': True}

        try:
            sales_result = import_ebay_sales.run(user_id, days_back=days_back)
        except Exception as e:
            log_task(f"  ✗ Sales refresh failed: {e}")
            sales_result = {'success': False, 'error': str(e)}

        try:
            finance_result = sync_ebay_finances_user.run(user_id, days_back=7)
        except Exception as e:
            log_task(f"  ✗ Finance refresh failed: {e}")
            finance_result = {'success': False, 'error': str(e)}

        try:
            reconcile_result = reconcile_sales_from_finances(
                user_id=user_id,
                days_back=7,
                fetch_taxes=False,
                force_recalculate=False,
                only_missing=True
            )
        except Exception as e:
            log_task(f"  ✗ Finance reconcile failed: {e}")
            reconcile_result = {'success': False, 'error': str(e)}

        setting = SystemSetting.query.filter_by(key=throttle_key).first()
        if not setting:
            setting = SystemSetting(key=throttle_key)
            db.session.add(setting)
        setting.value_int = now_ts
        db.session.commit()

        return {
            'success': True,
            'sales': sales_result,
            'finances': finance_result,
            'reconcile': reconcile_result
        }


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
        from qventory.helpers.ebay_inventory import (
            get_all_inventory,
            parse_ebay_inventory_item,
            get_listing_time_details,
            get_active_listings_trading_api,
            deduplicate_ebay_items
        )
        from qventory.helpers import generate_sku

        log_task(f"=== Starting eBay import for user {user_id} ===")
        log_task(f"Mode: {import_mode}, Status: {listing_status}")
        log_task(f"Task ID: {self.request.id}")

        # Check if there's already an import running for this user
        existing_job = ImportJob.query.filter(
            ImportJob.user_id == user_id,
            ImportJob.status.in_(['pending', 'processing'])
        ).first()

        if existing_job:
            log_task(f"⚠️  Import already running for user {user_id} (Job ID: {existing_job.id})")
            log_task(f"⚠️  Skipping this import to prevent duplicates")
            return {
                'success': False,
                'error': f'Import already in progress (Job ID: {existing_job.id})',
                'skipped': True
            }

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

            # Fetch inventory from eBay using multi-API fallback (Inventory + Offers + Trading)
            log_task("Fetching inventory from eBay API (Inventory/Offers/Trading)...")
            ebay_items = get_all_inventory(user_id, max_items=1000)
            failed_items = []  # get_all_inventory already returns normalized items
            ebay_items, duplicate_entries = deduplicate_ebay_items(ebay_items)
            log_task(f"Fetched {len(ebay_items)} unique items from eBay")
            if duplicate_entries:
                log_task(f"Removed {len(duplicate_entries)} duplicate entries before processing")

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
                    variation_skus = parsed.get('variation_skus') or []

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
                    if ebay_sku or variation_skus:
                        sku_list = []
                        if ebay_sku:
                            sku_list.append(ebay_sku)
                        for sku in variation_skus:
                            if sku and sku not in sku_list:
                                sku_list.append(sku)
                        log_task(f"  ✅ SKU(s) detected: {sku_list}")

                    # Trading API is the source of truth for Custom Label (Item.SKU)
                    if ebay_listing_id and ebay_item.get('source') != 'trading_api':
                        try:
                            from qventory.helpers.ebay_relist import get_item_details_trading_api
                            from qventory.helpers import is_valid_location_code, parse_location_code
                            trading_result = get_item_details_trading_api(user_id, ebay_listing_id)
                            trading_sku = (trading_result.get('item', {}) or {}).get('sku')
                            if trading_sku:
                                log_task(f"  ↳ Trading API SKU fallback: {trading_sku}")
                                ebay_item['sku'] = trading_sku
                                ebay_item['ebay_sku'] = trading_sku
                                parsed['ebay_sku'] = trading_sku
                                parsed['location_code'] = trading_sku
                                if is_valid_location_code(trading_sku):
                                    comps = parse_location_code(trading_sku)
                                    parsed['location_A'] = comps.get('A')
                                    parsed['location_B'] = comps.get('B')
                                    parsed['location_S'] = comps.get('S')
                                    parsed['location_C'] = comps.get('C')
                        except Exception as fallback_err:
                            log_task(f"  ⚠ Trading API SKU fallback failed: {fallback_err}")

                    # First try: Match by eBay Listing ID (active OR inactive to prevent duplicates)
                    if ebay_listing_id:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            ebay_listing_id=ebay_listing_id
                        ).first()
                        if existing_item:
                            match_method = "ebay_listing_id"

                    # Second try: Match by inactive item with this listing_id in notes (relisted item)
                    # This preserves supplier and other Qventory data when items are relisted
                    if not existing_item and ebay_listing_id:
                        # Look for inactive items where notes contains "Relisted as {ebay_listing_id}"
                        # This matches the new relist format we're using
                        inactive_relisted = Item.query.filter_by(
                            user_id=user_id,
                            is_active=False
                        ).filter(
                            or_(
                                Item.notes.like(f'%Relisted as {ebay_listing_id}%'),
                                Item.notes.like(f'%new listing ID: {ebay_listing_id}%')  # Legacy format
                            )
                        ).first()

                        if inactive_relisted:
                            log_task(f"  ✓ Found relisted item (Qventory ID: {inactive_relisted.id}, reactivating and updating)")
                            existing_item = inactive_relisted
                            # Reactivate the item since it's active on eBay again
                            existing_item.is_active = True
                            match_method = "relisted_item"

                    # Third try: Match by exact title (ONLY if no listing_id, least reliable fallback)
                    if not existing_item and ebay_title and not ebay_listing_id:
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

                            # REACTIVATE item if it was marked inactive (from relist)
                            if not existing_item.is_active and match_method == "relisted_item":
                                log_task(f"  ↻ Reactivating relisted item (preserving supplier: {existing_item.supplier_id})")
                                existing_item.is_active = True

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
                            # Always overwrite location_code from eBay Custom SKU when provided
                            location_code = parsed_with_images.get('location_code') or parsed.get('location_code')
                            if location_code is not None:
                                existing_item.location_code = location_code
                                existing_item.A = parsed_with_images.get('location_A') or parsed.get('location_A')
                                existing_item.B = parsed_with_images.get('location_B') or parsed.get('location_B')
                                existing_item.S = parsed_with_images.get('location_S') or parsed.get('location_S')
                                existing_item.C = parsed_with_images.get('location_C') or parsed.get('location_C')

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

                            # FINAL SAFETY CHECK: Verify no duplicate exists before creating
                            # This prevents race conditions where item was created between checks
                            final_listing_id = parsed_with_images.get('ebay_listing_id')
                            if final_listing_id:
                                duplicate_check = Item.query.filter_by(
                                    user_id=user_id,
                                    ebay_listing_id=final_listing_id
                                ).first()
                                if duplicate_check:
                                    log_task(f"  ⚠️  DUPLICATE DETECTED during final check! Item already exists (ID: {duplicate_check.id}). Skipping creation.")
                                    skipped_count += 1
                                    continue

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

            # Send completion notification to user
            try:
                from qventory.models.notification import Notification

                if plan_limit_reached:
                    # Plan limit reached - notify user to upgrade
                    Notification.create_notification(
                        user_id=user_id,
                        type='warning',
                        title='Plan Limit Reached',
                        message=f'We imported {imported_count} items from eBay, but you have more listings available. Upgrade your plan to import all your inventory.',
                        link_url='/settings',
                        link_text='Upgrade Plan',
                        source='ebay_import'
                    )
                    try:
                        from qventory.helpers.email_sender import send_plan_limit_reached_email
                        user = User.query.get(user_id)
                        if user:
                            max_items = user.get_plan_limits().max_items or 0
                            send_plan_limit_reached_email(user.email, user.username, max_items)
                    except Exception:
                        pass
                    log_task(f"✓ Sent plan limit notification")
                else:
                    # Import completed successfully
                    if imported_count > 0 or updated_count > 0:
                        Notification.create_notification(
                            user_id=user_id,
                            type='success',
                            title='eBay Import Completed',
                            message=f'Successfully imported {imported_count} new items and updated {updated_count} existing items from eBay.',
                            link_url='/inventory',
                            link_text='View Inventory',
                            source='ebay_import'
                        )
                        log_task(f"✓ Sent completion notification")
                    else:
                        # No new items found
                        Notification.create_notification(
                            user_id=user_id,
                            type='info',
                            title='eBay Import Completed',
                            message=f'Your eBay inventory is already up to date. No new items to import.',
                            link_url='/inventory',
                            link_text='View Inventory',
                            source='ebay_import'
                        )
                        log_task(f"✓ Sent 'no new items' notification")
            except Exception as notif_error:
                log_task(f"WARNING: Failed to send completion notification: {str(notif_error)}")

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
        import math
        import os

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
            if ebay_cred and ebay_store_monthly_fee is None:
                try:
                    from qventory.helpers.ebay_inventory import sync_ebay_store_subscription
                    store_result = sync_ebay_store_subscription(user_id)
                    if store_result.get('success'):
                        ebay_store_monthly_fee = store_result.get('monthly_fee', 0.0) or 0.0
                except Exception as store_error:
                    log_task(f"Store subscription lookup failed: {store_error}")
                    ebay_store_monthly_fee = 0.0
            if ebay_store_monthly_fee is None:
                ebay_store_monthly_fee = 0.0

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
                    shipping_charged = sale_data.get('shipping_charged')
                    tax_collected = sale_data.get('tax_collected')
                    buyer_username = sale_data.get('buyer_username', '')
                    tracking_number = sale_data.get('tracking_number')
                    carrier = sale_data.get('carrier')
                    shipped_at = sale_data.get('shipped_at')
                    delivered_at = sale_data.get('delivered_at')
                    sold_at = sale_data.get('sold_at') or shipped_at or delivered_at or datetime.utcnow()
                    status = sale_data.get('status', 'pending')
                    ebay_transaction_id = sale_data.get('ebay_transaction_id')
                    refund_amount = sale_data.get('refund_amount')
                    refund_reason = sale_data.get('refund_reason')

                    # Use real fees from Fulfillment API if available.
                    # Do NOT estimate — reconcile_sales_from_finances will fill
                    # accurate fees from the Finances API after this import.
                    marketplace_fee = sale_data.get('marketplace_fee') or 0
                    payment_fee = sale_data.get('payment_processing_fee') or 0
                    ad_fee = sale_data.get('ad_fee') or 0
                    other_fees = sale_data.get('other_fees') or 0

                    # Try to find matching item in Qventory (multiple strategies)
                    item = None
                    match_method = None

                    # Strategy 1: Match by eBay listing ID
                    ebay_listing_id = sale_data.get('ebay_listing_id')
                    if ebay_listing_id:
                        item = Item.query.filter_by(user_id=user_id, ebay_listing_id=ebay_listing_id).first()
                        if item:
                            match_method = "ebay_listing_id"

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
                        # Only set fees from Fulfillment API if available;
                        # reconcile_sales_from_finances will overwrite with
                        # accurate Finances API data later.
                        if marketplace_fee:
                            existing_sale.marketplace_fee = marketplace_fee
                        if payment_fee:
                            existing_sale.payment_processing_fee = payment_fee
                        if ad_fee:
                            existing_sale.ad_fee = ad_fee
                        if other_fees:
                            existing_sale.other_fees = other_fees
                        if shipping_cost is not None:
                            if shipping_cost > 0 or not existing_sale.shipping_cost:
                                existing_sale.shipping_cost = shipping_cost
                        if shipping_charged is not None:
                            existing_sale.shipping_charged = shipping_charged
                        if tax_collected is not None:
                            existing_sale.tax_collected = tax_collected
                        if refund_amount is not None:
                            existing_sale.refund_amount = refund_amount
                            existing_sale.refund_reason = refund_reason
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

                        # Mark item as sold if not already marked
                        if item and not item.sold_at:
                            item.is_active = False
                            item.sold_at = sold_at
                            item.sold_price = sold_price
                            log_task(f"    → Marked item as sold (soft delete)")
                            try:
                                from qventory.helpers.link_bio import remove_featured_items_for_user
                                remove_featured_items_for_user(user_id, [item.id])
                            except Exception:
                                pass

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
                            tax_collected=tax_collected,
                            item_cost=item.item_cost if item else None,
                            marketplace_fee=marketplace_fee,
                            payment_processing_fee=payment_fee,
                            ad_fee=ad_fee,
                            shipping_cost=shipping_cost,
                            shipping_charged=shipping_charged,
                            other_fees=other_fees,
                            sold_at=sold_at,
                            shipped_at=shipped_at,
                            delivered_at=delivered_at,
                            tracking_number=tracking_number,
                            carrier=carrier,
                            status=status,
                            buyer_username=buyer_username,
                            ebay_transaction_id=ebay_transaction_id,
                            ebay_buyer_username=buyer_username,
                            refund_amount=refund_amount,
                            refund_reason=refund_reason
                        )

                        # Mark item as sold if not already marked
                        if item and not item.sold_at:
                            item.is_active = False
                            item.sold_at = sold_at
                            item.sold_price = sold_price
                            log_task(f"    → Marked item as sold (soft delete)")
                            try:
                                from qventory.helpers.link_bio import remove_featured_items_for_user
                                remove_featured_items_for_user(user_id, [item.id])
                            except Exception:
                                pass

                        new_sale.calculate_profit()
                        db.session.add(new_sale)
                        imported_count += 1
                        total_fees_log = marketplace_fee + payment_fee + ad_fee + other_fees
                        log_task(f"  Imported sale: {title[:50]} - ${sold_price} (Fees: ${total_fees_log:.2f})")

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

                # Strategy 2: Match by SKU (non-eBay only)
                if not item and sku and sale.marketplace != 'ebay':
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


@celery.task(bind=True, name='qventory.tasks.resume_ebay_imports_after_upgrade')
def resume_ebay_imports_after_upgrade(self):
    """
    ONE-TIME TASK: Resume eBay imports for users who were upgraded but have incomplete imports

    This task should be run once after deploying the auto-resume feature to catch
    users who were upgraded before the auto-resume functionality existed.

    Looks for users who:
    - Have a paid plan (early_adopter, premium, pro, god)
    - Have eBay connected
    - Have items_remaining > 0 (space for more items)
    - Were upgraded recently (within last 30 days)

    Returns:
        dict: Summary of resume operations
    """
    app = create_app()

    with app.app_context():
        from qventory.models.user import User
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.subscription import Subscription
        from datetime import datetime, timedelta

        log_task("=== Resume eBay imports for upgraded users (ONE-TIME) ===")

        # Get all users with paid plans
        paid_roles = ['early_adopter', 'premium', 'pro', 'god']
        users = User.query.filter(User.role.in_(paid_roles)).all()

        log_task(f"Found {len(users)} users with paid plans")

        resumed_count = 0
        skipped_no_ebay = 0
        skipped_no_space = 0
        errors = []

        for user in users:
            try:
                # Check if user has eBay connected
                ebay_cred = MarketplaceCredential.query.filter_by(
                    user_id=user.id,
                    marketplace='ebay',
                    is_active=True
                ).first()

                if not ebay_cred:
                    skipped_no_ebay += 1
                    continue

                # Check if user has space for more items
                items_remaining = user.items_remaining()

                if items_remaining is None:
                    # Unlimited - always try to import
                    log_task(f"  User {user.username} ({user.role}): Unlimited plan, resuming import...")
                elif items_remaining > 0:
                    log_task(f"  User {user.username} ({user.role}): {items_remaining} slots available, resuming import...")
                else:
                    skipped_no_space += 1
                    log_task(f"  User {user.username} ({user.role}): No space available (0/{user.get_plan_limits().max_items})")
                    continue

                # Launch import task
                import_ebay_inventory.delay(user.id, import_mode='new_only', listing_status='ACTIVE')
                resumed_count += 1

                log_task(f"    ✓ Import task launched for user {user.username}")

            except Exception as e:
                log_task(f"  ✗ Error processing user {user.id}: {str(e)}")
                errors.append(f"User {user.id}: {str(e)}")

        log_task(f"=== Resume complete: {resumed_count} imports launched, {skipped_no_ebay} no eBay, {skipped_no_space} no space ===")

        return {
            'success': True,
            'resumed': resumed_count,
            'skipped_no_ebay': skipped_no_ebay,
            'skipped_no_space': skipped_no_space,
            'total_paid_users': len(users),
            'errors': errors
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
                history.sku = rule.sku
                history.old_title = rule.item_title
                try:
                    from qventory.models.item import Item
                    item_match = None
                    if rule.sku:
                        item_match = Item.query.filter_by(user_id=rule.user_id, sku=rule.sku).first()
                    if not item_match and rule.listing_id:
                        item_match = Item.query.filter_by(
                            user_id=rule.user_id,
                            ebay_listing_id=rule.listing_id
                        ).first()
                    if item_match:
                        history.item_id = item_match.id
                except Exception as match_err:
                    log_task(f"  ⚠ Unable to link relist history to item: {match_err}")
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

                if apply_changes and rule.pending_changes:
                    history.changes_applied = rule.pending_changes.copy()
                    # Capture new price if changed
                    if 'price' in rule.pending_changes:
                        history.new_price = rule.pending_changes['price']
                    if 'title' in rule.pending_changes:
                        history.new_title = rule.pending_changes['title']

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

        # Mark item as sold if not already marked
        if item and not item.sold_at:
            item.is_active = False
            item.sold_at = datetime.utcnow()
            item.sold_price = sold_price
            log_task(f"  → Marked item as sold (soft delete)")
            try:
                from qventory.helpers.link_bio import remove_featured_items_for_user
                remove_featured_items_for_user(event.user_id, [item.id])
            except Exception:
                pass

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
        from qventory.models.system_setting import SystemSetting
        from datetime import datetime, timedelta
        import math
        import os
        import requests

        log_task("=== Polling eBay for new listings ===")

        cooldown_until_ts = SystemSetting.get_int('ebay_polling_cooldown_until')
        if cooldown_until_ts:
            now_ts = int(datetime.utcnow().timestamp())
            if now_ts < cooldown_until_ts:
                cooldown_until = datetime.utcfromtimestamp(cooldown_until_ts)
                log_task(f"Polling paused due to rate limit cooldown until {cooldown_until.isoformat()} UTC")
                return {
                    'success': True,
                    'users_checked': 0,
                    'new_listings': 0,
                    'errors': 0,
                    'cooldown_until': cooldown_until.isoformat()
                }

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

        # Smart polling: Filter to only "active" users and not in cooldown
        active_credentials = []
        user_map = {}
        now = datetime.utcnow()
        for cred in credentials:
            user = User.query.get(cred.user_id)
            if not user or not should_poll_user(user, cred):
                continue
            cooldown_until = getattr(cred, 'poll_cooldown_until', None)
            if cooldown_until and cooldown_until > now:
                continue
            active_credentials.append(cred)
            user_map[cred.user_id] = user.username or f"user_{cred.user_id}"

        log_task(f"Found {len(active_credentials)} active users to check (out of {len(credentials)} total)")

        def _get_poll_batch(all_creds, batch_size=20, interval_seconds=300):
            if not all_creds:
                return []
            total_batches = (len(all_creds) + batch_size - 1) // batch_size
            if total_batches <= 1:
                return all_creds
            # Persistent cursor to rotate batches even if interval is misconfigured
            cursor = SystemSetting.get_int('ebay_polling_batch_cursor', 0) or 0
            batch_index = cursor % total_batches
            SystemSetting.set_int('ebay_polling_batch_cursor', cursor + 1)
            rotated = all_creds
            start_idx = batch_index * batch_size
            end_idx = min(start_idx + batch_size, len(rotated))
            return rotated[start_idx:end_idx]

        # Batch users per execution to control API usage (adaptive batch size)
        active_count = len(active_credentials)
        interval_seconds = int(os.environ.get('POLL_INTERVAL_SECONDS', 60))
        target_minutes = int(os.environ.get('POLL_TARGET_COVERAGE_MINUTES', 10))
        min_batch_size = int(os.environ.get('POLL_MIN_BATCH_SIZE', 5))
        max_batch_size = int(os.environ.get('POLL_MAX_BATCH_SIZE', 100))

        target_batches = max(1, math.ceil((target_minutes * 60) / max(1, interval_seconds)))
        if active_count == 0:
            batch_size = 0
        else:
            batch_size = math.ceil(active_count / target_batches)
            batch_size = max(min_batch_size, batch_size)
            batch_size = min(max_batch_size, batch_size)

        batch_credentials = _get_poll_batch(
            active_credentials,
            batch_size=batch_size or 1,
            interval_seconds=interval_seconds
        )
        batch_usernames = []
        for cred in batch_credentials:
            batch_usernames.append(user_map.get(cred.user_id, f"user_{cred.user_id}"))
        usernames_csv = ", ".join(batch_usernames) if batch_usernames else "-"

        log_task(
            f"Processing polling batch of {len(batch_credentials)} users "
            f"(active={active_count}, batch_size={batch_size}, target_minutes={target_minutes}) "
            f"users=[{usernames_csv}]"
        )

        total_new = 0
        total_errors = 0

        for cred in batch_credentials:
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

    SCALABLE ADAPTIVE POLLING — budget: ~5,000 Trading API calls/day shared
    across GetSellerEvents + GetMyeBaySelling + GetItem (images).

    Tiers (task runs every 5 minutes):
    - VERY active (item in last hour): poll every 5 min  → 288 calls/day
    - Active (activity < 6 hours): poll every 15 min     → 96 calls/day
    - Normal (activity < 24 hours): poll every 30 min    → 48 calls/day
    - Semi-active (activity < 7 days): poll every 2 hours → 12 calls/day
    - Inactive: poll every 12 hours                       → 2 calls/day

    With 20 users: ~288*2 + 96*3 + 48*5 + 12*5 + 2*5 = ~1,474 calls/day
    Leaves ~3,500 calls/day for inventory sync + GetItem + admin tasks.

    Args:
        user: User object
        credential: MarketplaceCredential object

    Returns:
        bool: True if should poll now
    """
    from datetime import datetime, timedelta
    from qventory.models.item import Item

    now = datetime.utcnow()
    last_poll = getattr(credential, 'last_poll_at', None)

    # First time polling - always check
    if not last_poll:
        return True

    # TIER 1: VERY ACTIVE - User created item in last hour → Poll every 5 min
    very_recent_activity = Item.query.filter_by(user_id=user.id).filter(
        Item.created_at > (now - timedelta(hours=1))
    ).first()
    if very_recent_activity:
        return (now - last_poll) >= timedelta(minutes=5)

    # TIER 2: ACTIVE - User activity < 6 hours → Poll every 15 minutes
    if user.last_activity and (now - user.last_activity) < timedelta(hours=6):
        return (now - last_poll) >= timedelta(minutes=15)

    # TIER 3: NORMAL - User activity < 24 hours → Poll every 30 minutes
    if user.last_activity and (now - user.last_activity) < timedelta(hours=24):
        return (now - last_poll) >= timedelta(minutes=30)

    # TIER 4: SEMI-ACTIVE - User activity < 7 days → Poll every 2 hours
    if user.last_activity and (now - user.last_activity) < timedelta(days=7):
        return (now - last_poll) >= timedelta(hours=2)

    # TIER 5: INACTIVE - User activity > 7 days → Poll every 12 hours
    return (now - last_poll) >= timedelta(hours=12)


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
        # Also update token_expires_at so get_user_access_token() knows when to refresh
        from datetime import timedelta
        credential.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 7200))
        db.session.commit()

        return {'success': True}

    except Exception as e:
        log_task(f"    Token refresh exception: {str(e)}")
        return {'success': False, 'error': str(e)}


def poll_user_listings(credential):
    """
    Poll eBay GetSellerEvents for a single user (delta-only)

    Fetches new listings since last poll and imports only missing ones.
    Uses Trading API GetItem per new listing to enrich with title, images, and price.

    Args:
        credential: MarketplaceCredential object

    Returns:
        dict: {'new_listings': int, 'errors': []}
    """
    from datetime import datetime, timedelta
    from qventory.models.item import Item
    from qventory.models.polling_log import PollingLog
    from qventory.models.system_setting import SystemSetting
    from qventory.helpers import generate_sku
    from qventory.helpers.ebay_inventory import TRADING_API_URL, get_listing_details_trading_api, parse_ebay_inventory_item
    from qventory.extensions import db
    import os
    import requests
    import xml.etree.ElementTree as ET

    user_id = credential.user_id

    # Determine polling window early for logging
    now = datetime.utcnow()
    last_poll = getattr(credential, 'last_poll_at', None)
    if last_poll:
        time_from = last_poll - timedelta(minutes=2)  # overlap to avoid misses
    else:
        time_from = now - timedelta(minutes=10)
    if time_from < now - timedelta(hours=24):
        time_from = now - timedelta(hours=24)
    time_to = now

    poll_log = PollingLog(
        user_id=user_id,
        marketplace='ebay',
        started_at=now,
        window_start=time_from,
        window_end=time_to,
        status='running'
    )
    db.session.add(poll_log)
    db.session.flush()

    def finalize_poll(status, new_count=0, errors=None):
        poll_log.ended_at = datetime.utcnow()
        poll_log.status = status
        poll_log.new_listings = new_count
        if errors:
            poll_log.errors_count = len(errors)
            poll_log.error_message = "; ".join([str(e) for e in errors])[:2000]
        db.session.commit()

    try:
        def _is_rate_limit_error(message: str) -> bool:
            if not message:
                return False
            msg = message.lower()
            return (
                'exceeded usage limit' in msg
                or 'call usage' in msg
                or 'rate limit' in msg
                or 'throttl' in msg
                or '429' in msg
            )

        # Check if token needs refresh (eBay tokens expire after 2 hours)
        # We'll refresh if token is older than 1.5 hours to be safe
        token_age = datetime.utcnow() - credential.created_at
        if token_age > timedelta(hours=1, minutes=30):
            log_task(f"    Token is {token_age.total_seconds()/3600:.1f}h old, refreshing...")
            refresh_result = refresh_ebay_token(credential)
            if not refresh_result['success']:
                log_task(f"    ✗ Token refresh failed: {refresh_result.get('error', 'Unknown error')}")
                # Cooldown this credential for 24h to avoid repeated failures
                credential.poll_cooldown_until = datetime.utcnow() + timedelta(hours=24)
                credential.poll_cooldown_reason = 'token_refresh_failed'
                db.session.commit()
                finalize_poll('error', errors=['Token refresh failed'])
                return {'new_listings': 0, 'errors': ['Token refresh failed']}
            log_task(f"    ✓ Token refreshed successfully")

        # Check user's plan limits
        from qventory.models.user import User
        user = User.query.get(user_id)
        if not user:
            log_task(f"    ✗ User {user_id} not found")
            finalize_poll('error', errors=['User not found'])
            return {'new_listings': 0, 'errors': ['User not found']}

        items_remaining = user.items_remaining()
        log_task(f"    User plan: {user.role}, Items remaining: {items_remaining}")

        if items_remaining is not None and items_remaining <= 0:
            log_task(f"    ⚠ User has reached plan limit (0 items remaining); will skip new imports but still sync changes")

        access_token = credential.get_access_token()
        if not access_token:
            log_task(f"    ✗ No access token for user {user_id}")
            finalize_poll('error', errors=['No access token'])
            return {'new_listings': 0, 'errors': ['No access token']}

        log_task(f"    Polling window: {time_from.isoformat()} -> {time_to.isoformat()}")

        ebay_app_id = os.environ.get('EBAY_CLIENT_ID')
        ebay_dev_id = os.environ.get('EBAY_DEV_ID')
        ebay_cert_id = os.environ.get('EBAY_CERT_ID')
        if not (ebay_app_id and ebay_dev_id and ebay_cert_id):
            log_task("    ✗ Missing Trading API credentials (EBAY_CLIENT_ID/DEV_ID/CERT_ID)")
            finalize_poll('error', errors=['Missing Trading API credentials'])
            return {'new_listings': 0, 'errors': ['Missing Trading API credentials']}

        ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
        new_listings = 0
        last_title = None
        remaining_quota = items_remaining if items_remaining is not None else None
        seen_listing_ids = set()

        # GetSellerEvents does NOT support Pagination (max 2000 items with ReturnAll).
        # For delta polling with small time windows this is sufficient.
        xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetSellerEventsRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <StartTimeFrom>{time_from.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</StartTimeFrom>
  <StartTimeTo>{time_to.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</StartTimeTo>
  <EndTimeFrom>{time_from.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</EndTimeFrom>
  <EndTimeTo>{time_to.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</EndTimeTo>
  <ModTimeFrom>{time_from.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</ModTimeFrom>
  <ModTimeTo>{time_to.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</ModTimeTo>
  <DetailLevel>ReturnAll</DetailLevel>
</GetSellerEventsRequest>'''

        headers = {
            'X-EBAY-API-COMPATIBILITY-LEVEL': '1193',
            'X-EBAY-API-DEV-NAME': ebay_dev_id,
            'X-EBAY-API-APP-NAME': ebay_app_id,
            'X-EBAY-API-CERT-NAME': ebay_cert_id,
            'X-EBAY-API-CALL-NAME': 'GetSellerEvents',
            'X-EBAY-API-SITEID': '0',
            'X-EBAY-API-IAF-TOKEN': access_token,
            'Content-Type': 'text/xml'
        }

        response = requests.post(TRADING_API_URL, data=xml_request, headers=headers, timeout=30)
        if response.status_code != 200:
            log_task(f"    GetSellerEvents failed: HTTP {response.status_code}")
            if response.status_code == 429 or _is_rate_limit_error(response.text or ''):
                credential.poll_cooldown_until = datetime.utcnow() + timedelta(hours=2)
                credential.poll_cooldown_reason = 'rate_limit'
                db.session.commit()
                SystemSetting.set_int(
                    'ebay_polling_cooldown_until',
                    int((datetime.utcnow() + timedelta(hours=2)).timestamp())
                )
            finalize_poll('error', errors=[f'HTTP {response.status_code}'])
            return {'new_listings': 0, 'errors': [f'HTTP {response.status_code}']}

        root = ET.fromstring(response.text)
        ack = root.find('ebay:Ack', ns)
        if ack is None or ack.text not in ['Success', 'Warning']:
            errors = root.findall('.//ebay:Errors', ns)
            error_msgs = [
                e.find('ebay:LongMessage', ns).text
                for e in errors
                if e.find('ebay:LongMessage', ns) is not None
            ]
            log_task(f"    GetSellerEvents error: {'; '.join(error_msgs)}")
            if any(_is_rate_limit_error(msg or '') for msg in error_msgs):
                credential.poll_cooldown_until = datetime.utcnow() + timedelta(hours=2)
                credential.poll_cooldown_reason = 'rate_limit'
                db.session.commit()
                SystemSetting.set_int(
                    'ebay_polling_cooldown_until',
                    int((datetime.utcnow() + timedelta(hours=2)).timestamp())
                )
            finalize_poll('error', errors=error_msgs)
            return {'new_listings': 0, 'errors': error_msgs}

        items = root.findall('.//ebay:ItemArray/ebay:Item', ns)
        if items:
            log_task(f"    GetSellerEvents returned {len(items)} item(s)")
        for item_elem in items:
            item_id_elem = item_elem.find('ebay:ItemID', ns)
            title_elem = item_elem.find('ebay:Title', ns)
            if item_id_elem is None or not item_id_elem.text:
                continue
            listing_id = item_id_elem.text.strip()
            if listing_id in seen_listing_ids:
                continue
            seen_listing_ids.add(listing_id)

            listing_status_elem = item_elem.find('ebay:ListingStatus', ns)
            listing_status = listing_status_elem.text.strip() if listing_status_elem is not None and listing_status_elem.text else None

            existing = Item.query.filter_by(
                user_id=user_id,
                ebay_listing_id=listing_id
            ).first()
            if existing:
                # If price is missing, backfill via Trading API even if no changes detected
                if existing.item_price is None:
                    enriched_missing_price = get_listing_details_trading_api(user_id, listing_id) or {}
                    if enriched_missing_price:
                        parsed_missing = parse_ebay_inventory_item(enriched_missing_price, process_images=True)
                        backfill_price = parsed_missing.get('item_price')
                        backfill_thumb = parsed_missing.get('item_thumb')
                        backfill_title = (parsed_missing.get('title') or '').strip()
                        if backfill_price is not None:
                            existing.item_price = backfill_price
                        if backfill_thumb and not existing.item_thumb:
                            existing.item_thumb = backfill_thumb
                        if backfill_title and backfill_title != (existing.title or '').strip():
                            existing.title = backfill_title[:500]
                        if backfill_price is not None or backfill_thumb or backfill_title:
                            existing.last_ebay_sync = datetime.utcnow()
                            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                            existing.notes = (existing.notes or '') + f"\n[{timestamp}] Price backfilled from eBay"
                            db.session.commit()

                # If the listing ended, mark inactive and note it
                if listing_status and listing_status.lower() in ['ended', 'completed', 'closed']:
                    if existing.is_active:
                        existing.is_active = False
                        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                        end_note = f"\n[{timestamp}] Listing ended on eBay (status: {listing_status})"
                        existing.notes = (existing.notes or '') + end_note
                        try:
                            from qventory.helpers.link_bio import remove_featured_items_for_user
                            remove_featured_items_for_user(user_id, [existing.id])
                        except Exception:
                            pass
                        db.session.commit()
                        log_task(f"    ⊗ Marked inactive (ended on eBay): {existing.sku} (eBay ID: {listing_id})")
                    continue

                # Existing listing updated/revised: refresh details and record history
                enriched_existing = get_listing_details_trading_api(user_id, listing_id) or {}
                if enriched_existing:
                    parsed_existing = parse_ebay_inventory_item(enriched_existing, process_images=True)
                    new_title = (parsed_existing.get('title') or '').strip()
                    new_price = parsed_existing.get('item_price')
                    new_thumb = parsed_existing.get('item_thumb')

                    changes = []
                    if new_title and new_title != (existing.title or '').strip():
                        existing.title = new_title[:500]
                        changes.append("title")
                    if new_price is not None and existing.item_price != new_price:
                        existing.item_price = new_price
                        changes.append("price")
                    if new_thumb and not existing.item_thumb:
                        existing.item_thumb = new_thumb
                        changes.append("image")

                    if changes:
                        existing.last_ebay_sync = datetime.utcnow()
                        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                        change_note = f"\n[{timestamp}] Listing updated from eBay ({', '.join(changes)})"
                        existing.notes = (existing.notes or '') + change_note
                        db.session.commit()
                        log_task(f"    ↻ Updated existing listing {listing_id}: {', '.join(changes)}")
                continue

            if remaining_quota is not None and remaining_quota <= 0:
                log_task(f"    ✗ User reached plan limit while importing new listings")
                break

            # Enrich with GetItem for full details (title, images, price, sku)
            enriched = get_listing_details_trading_api(user_id, listing_id) or {}
            if not enriched:
                title_text = title_elem.text.strip() if title_elem is not None and title_elem.text else 'eBay Item'
                price = None
                bin_price_elem = item_elem.find('ebay:BuyItNowPrice', ns)
                start_price_elem = item_elem.find('ebay:StartPrice', ns)
                for price_elem in (bin_price_elem, start_price_elem):
                    if price_elem is not None and price_elem.text:
                        try:
                            price = float(price_elem.text)
                            break
                        except (TypeError, ValueError):
                            pass

                sku_elem = item_elem.find('ebay:SKU', ns)
                ebay_sku = sku_elem.text.strip() if sku_elem is not None and sku_elem.text else ''

                view_url_elem = item_elem.find('ebay:ListingDetails/ebay:ViewItemURL', ns)
                view_url = view_url_elem.text if view_url_elem is not None else f'https://www.ebay.com/itm/{listing_id}'

                enriched = {
                    'sku': ebay_sku,
                    'product': {
                        'title': title_text,
                        'description': '',
                        'imageUrls': []
                    },
                    'availability': {
                        'shipToLocationAvailability': {
                            'quantity': 1
                        }
                    },
                    'condition': 'USED_EXCELLENT',
                    'ebay_listing_id': listing_id,
                    'item_price': price,
                    'ebay_url': view_url,
                    'source': 'trading_api'
                }

            parsed_with_images = parse_ebay_inventory_item(enriched, process_images=True)

            title = parsed_with_images.get('title', 'eBay Item')
            ebay_custom_sku = parsed_with_images.get('ebay_sku')
            price = parsed_with_images.get('item_price')
            listing_url = parsed_with_images.get('ebay_url', f'https://www.ebay.com/itm/{listing_id}')
            item_thumb = parsed_with_images.get('item_thumb')
            location_code = parsed_with_images.get('location_code') or ebay_custom_sku
            quantity = parsed_with_images.get('quantity')

            relist_source = Item.query.filter_by(user_id=user_id).filter(
                Item.notes.like(f'%Relist pending: {listing_id}%')
            ).order_by(Item.updated_at.desc()).first()

            new_item = Item(
                user_id=user_id,
                title=title[:500] if title else 'eBay Item',
                sku=generate_sku(),
                ebay_listing_id=listing_id,
                ebay_sku=ebay_custom_sku[:100] if ebay_custom_sku else None,
                location_code=location_code,
                A=parsed_with_images.get('location_A'),
                B=parsed_with_images.get('location_B'),
                S=parsed_with_images.get('location_S'),
                C=parsed_with_images.get('location_C'),
                listing_link=listing_url,
                ebay_url=listing_url,
                item_price=price,
                item_thumb=item_thumb,
                quantity=quantity or 1,
                synced_from_ebay=True,
                last_ebay_sync=datetime.utcnow(),
                notes=f"Auto-imported from eBay on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} via polling"
            )
            if relist_source:
                new_item.previous_item_id = relist_source.id

            try:
                db.session.add(new_item)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                if "uq_items_user_ebay_listing" in str(e):
                    log_task(f"    Skipping duplicate listing {listing_id} (already exists)")
                    continue
                raise

            new_listings += 1
            last_title = title
            if remaining_quota is not None:
                remaining_quota -= 1

            log_task(f"    ✓ New listing: {title[:50]}")

            if relist_source:
                new_item.item_cost = relist_source.item_cost
                new_item.supplier = relist_source.supplier
                new_item.A = relist_source.A
                new_item.B = relist_source.B
                new_item.S = relist_source.S
                new_item.C = relist_source.C
                new_item.location_code = relist_source.location_code
                relist_source.is_active = False
                timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                relist_note = f"\n[{timestamp}] Relist transfer to {listing_id} completed"
                relist_source.notes = (relist_source.notes or '') + relist_note
                new_item.notes = (new_item.notes or '') + f"\n[{timestamp}] Relisted from {relist_source.ebay_listing_id or relist_source.id}"
                try:
                    from qventory.helpers.link_bio import remove_featured_items_for_user
                    remove_featured_items_for_user(user_id, [relist_source.id])
                except Exception:
                    pass
                db.session.commit()
                log_task(
                    f"    ✓ Transferred cost/supplier/location from {relist_source.id} "
                    f"to new listing {listing_id} (supplier: {relist_source.supplier})"
                )
            else:
                log_task(f"    ⚠ No relist source found for new listing {listing_id}")

        if new_listings > 0:
            from qventory.models.notification import Notification
            if new_listings == 1:
                Notification.create_notification(
                    user_id=user_id,
                    type='success',
                    title='New eBay listing imported!',
                    message=f'{(last_title or "New listing")[:50]} was automatically imported',
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

        credential.last_poll_at = datetime.utcnow()
        db.session.commit()

        finalize_poll('success', new_count=new_listings, errors=[])

        try:
            refresh_user_analytics.apply_async(args=[user_id], priority=9)
            log_task("    ↻ Analytics refresh queued")
        except Exception as analytics_err:
            log_task(f"    ⚠ Analytics refresh queue failed: {analytics_err}")

        return {
            'new_listings': new_listings,
            'errors': []
        }

    except Exception as e:
        log_task(f"    ✗ Exception: {str(e)}")
        import traceback
        log_task(f"    Traceback: {traceback.format_exc()}")
        finalize_poll('error', errors=[str(e)])
        return {'new_listings': 0, 'errors': [str(e)]}


# ==================== AUTO-SYNC HELPERS (PHASE 1 - SCALABLE) ====================

def get_active_users_with_ebay(hours_since_login=24):
    """
    Get users who were recently active and have active eBay credentials

    Used by auto-sync tasks to filter only recently active users.
    This reduces API load and focuses on users who are actively using the platform.

    IMPORTANT: Uses last_activity (any authenticated request) not last_login (explicit login).
    This properly handles users with long-lived session cookies (30 days).

    Args:
        hours_since_login (int): Max hours since last activity (default 24)
                                 Note: Parameter name kept for backward compatibility

    Returns:
        list: List of tuples (user, credential)
    """
    from qventory.models.user import User
    from qventory.models.marketplace_credential import MarketplaceCredential
    from datetime import datetime, timedelta

    cutoff_time = datetime.utcnow() - timedelta(hours=hours_since_login)

    # Get users with recent activity (any authenticated request)
    # This includes users with valid session cookies who haven't logged in recently
    active_users = User.query.filter(
        User.last_activity.isnot(None),
        User.last_activity > cutoff_time
    ).all()

    # Fallback: if no users with last_activity, try last_login
    # This handles migration period where last_activity might not be populated yet
    if not active_users:
        active_users = User.query.filter(
            User.last_login.isnot(None),
            User.last_login > cutoff_time
        ).all()

    # Get their eBay credentials if active
    result = []
    for user in active_users:
        credential = MarketplaceCredential.query.filter_by(
            user_id=user.id,
            marketplace='ebay',
            is_active=True
        ).first()

        if credential:
            result.append((user, credential))

    return result


def get_user_batch(all_users, batch_size=20, cursor_key=None):
    """
    Get current batch of users to process.

    When cursor_key is provided, uses a persistent cursor in SystemSetting
    to rotate through batches reliably across executions (ideal for tasks
    that don't run at predictable minute intervals, e.g. daily crontabs).

    Without cursor_key, falls back to minute-based rotation (for frequent tasks).

    Args:
        all_users (list): List of all users to batch
        batch_size (int): Users per batch (default 20)
        cursor_key (str): SystemSetting key for persistent batch cursor (optional)

    Returns:
        list: Current batch of users
    """
    from datetime import datetime

    if not all_users:
        return []

    total_batches = (len(all_users) + batch_size - 1) // batch_size

    if total_batches == 0:
        return all_users

    if cursor_key:
        from qventory.models.system_setting import SystemSetting
        setting = SystemSetting.query.filter_by(key=cursor_key).first()
        batch_index = int(setting.value) % total_batches if setting else 0

        # Advance cursor for the next execution
        next_index = (batch_index + 1) % total_batches
        if setting:
            setting.value = str(next_index)
        else:
            db.session.add(SystemSetting(key=cursor_key, value=str(next_index)))
        db.session.commit()
    else:
        # Fallback: minute-based rotation (for frequent tasks like every 15 min)
        current_minute = datetime.utcnow().minute
        batch_index = (current_minute // 15) % total_batches

    start_idx = batch_index * batch_size
    end_idx = min(start_idx + batch_size, len(all_users))

    return all_users[start_idx:end_idx]


# ==================== AUTO-SYNC TASKS ====================

@celery.task(bind=True, name='qventory.tasks.sync_ebay_active_inventory_auto')
def sync_ebay_active_inventory_auto(self):
    """
    Auto-sync active inventory for recently active users
    
    Updates prices, statuses, and removes sold items automatically.
    Uses batching to handle 100+ users without exceeding eBay API limits.
    
    Runs: Every 4 hours (6x/day)
    Batch: 20 users per execution (persistent cursor rotates through all users)
    API Calls: ~20-40 per execution
    
    Returns:
        dict: Summary of sync operations
    """
    app = create_app()
    
    with app.app_context():
        from qventory.models.item import Item
        from qventory.helpers.ebay_inventory import fetch_active_listings_snapshot
        from sqlalchemy import or_
        
        log_task("=== Auto-sync active inventory ===")
        
        # Get active users (logged in < 24 hours)
        all_active_users = get_active_users_with_ebay(hours_since_login=24)
        
        if not all_active_users:
            log_task("No active users to sync")
            return {
                'success': True,
                'users_processed': 0,
                'items_updated': 0,
                'items_deleted': 0
            }
        
        log_task(f"Found {len(all_active_users)} active users total")
        
        # Get current batch (20 users max to avoid API limits)
        # Uses persistent cursor so each execution processes the next batch
        batch_users = get_user_batch(all_active_users, batch_size=20, cursor_key='sync_inventory_batch_cursor')
        log_task(f"Processing batch of {len(batch_users)} users")
        
        total_updated = 0
        total_deleted = 0
        users_processed = 0
        
        for user, credential in batch_users:
            try:
                log_task(f"  Syncing user {user.id} ({user.username})...")
                
                # Get items with eBay listings
                items_to_sync = Item.query.filter(
                    Item.user_id == user.id,
                    Item.ebay_listing_id.isnot(None)
                ).all()
                
                if not items_to_sync:
                    log_task(f"    No items to sync")
                    continue
                
                snapshot = fetch_active_listings_snapshot(user.id)

                if not snapshot['success']:
                    log_task(f"    ✗ Failed to fetch eBay data: {snapshot.get('error')}")
                    continue

                offers = snapshot.get('offers', [])
                can_mark_inactive = snapshot.get('can_mark_inactive', False)
                sources = ', '.join(snapshot.get('sources', [])) or 'unknown'
                log_task(f"    Sources: {sources} | offers: {len(offers)} | can_mark_inactive={can_mark_inactive}")

                offers_by_listing = {
                    offer.get('ebay_listing_id'): offer
                    for offer in offers
                    if offer.get('ebay_listing_id')
                }

                # Safety check: if the snapshot has significantly fewer items than
                # what we have active in the DB, the API likely returned incomplete
                # data even though it reported success. Do NOT mass-inactivate.
                active_ebay_items_in_db = sum(1 for i in items_to_sync if i.is_active)
                snapshot_count = len(offers_by_listing)
                if can_mark_inactive and active_ebay_items_in_db > 0 and snapshot_count > 0:
                    coverage_ratio = snapshot_count / active_ebay_items_in_db
                    if coverage_ratio < 0.85:
                        log_task(f"    ⚠ Safety override: snapshot has {snapshot_count} items but DB has {active_ebay_items_in_db} active "
                                 f"({coverage_ratio:.0%} coverage). Skipping inactivation to prevent false positives.")
                        can_mark_inactive = False

                if not can_mark_inactive:
                    log_task("    Incomplete data; items not found will remain active")
                
                updated_count = 0
                deleted_count = 0

                for item in items_to_sync:
                    offer_data = None

                    if item.ebay_listing_id and item.ebay_listing_id in offers_by_listing:
                        offer_data = offers_by_listing[item.ebay_listing_id]

                    if offer_data:
                        if not item.is_active:
                            item.is_active = True
                            updated_count += 1

                        # Item still exists - update price
                        if offer_data.get('item_price') and offer_data['item_price'] != item.item_price:
                            item.item_price = offer_data['item_price']
                            updated_count += 1

                        # Listing still present in active snapshot; keep active.
                    else:
                        # Only mark items inactive if we are confident we fetched the full offer set
                        if can_mark_inactive:
                            # SOFT DELETE: Item no longer on eBay (sold/removed) - mark as inactive
                            # Don't mark as sold_at here - that will be set by sync_ebay_sold_orders_auto
                            if item.is_active:
                                item.is_active = False
                                try:
                                    from qventory.helpers.link_bio import remove_featured_items_for_user
                                    remove_featured_items_for_user(user.id, [item.id])
                                except Exception:
                                    pass
                                deleted_count += 1
                
                db.session.commit()

                # Backfill prices for active items still missing a price (max 5 per user to limit API calls)
                priceless_items = [
                    i for i in items_to_sync
                    if i.is_active and i.item_price is None and i.ebay_listing_id
                ]
                backfilled = 0
                if priceless_items:
                    from qventory.helpers.ebay_inventory import get_listing_details_trading_api, parse_ebay_inventory_item
                    for priceless in priceless_items[:5]:
                        try:
                            enriched = get_listing_details_trading_api(user.id, priceless.ebay_listing_id) or {}
                            if enriched:
                                parsed = parse_ebay_inventory_item(enriched, process_images=False)
                                if parsed.get('item_price') is not None:
                                    priceless.item_price = parsed['item_price']
                                    backfilled += 1
                                if parsed.get('item_thumb') and not priceless.item_thumb:
                                    priceless.item_thumb = parsed['item_thumb']
                                if parsed.get('title') and not priceless.title:
                                    priceless.title = parsed['title'][:500]
                        except Exception:
                            pass
                    if backfilled:
                        db.session.commit()

                log_task(f"    ✓ {updated_count} updated, {deleted_count} marked inactive, {backfilled} prices backfilled")
                total_updated += updated_count + backfilled
                total_deleted += deleted_count
                users_processed += 1

            except Exception as e:
                log_task(f"    ✗ Error syncing user {user.id}: {str(e)}")
                db.session.rollback()
                continue
        
        log_task(f"=== Sync complete: {users_processed} users, {total_updated} updated, {total_deleted} marked inactive ===")
        
        return {
            'success': True,
            'users_processed': users_processed,
            'items_updated': total_updated,
            'items_deleted': total_deleted
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_sold_orders_auto')
def sync_ebay_sold_orders_auto(self):
    """
    Auto-sync sold orders for recently active users (FREQUENT/QUICK SYNC)

    Fetches recent sold orders (last 2 hours) and updates sales database.
    Uses batching to handle 100+ users without exceeding eBay API limits.

    Runs: Every 15 minutes (8x more frequent for real-time updates)
    Batch: 20 users per execution (100 users = 5 batches = 75 minute cycle)
    API Calls: ~20-40 per execution
    Range: Last 2 hours only (focused on recent sales for real-time updates)

    Note: Complemented by sync_ebay_sold_orders_deep() which runs daily
          to catch older sales that may have been missed.

    Returns:
        dict: Summary of sync operations
    """
    app = create_app()

    with app.app_context():
        from qventory.helpers.ebay_inventory import fetch_ebay_sold_orders
        from qventory.models.sale import Sale
        from qventory.models.item import Item
        from datetime import datetime

        log_task("=== Quick-sync sold orders (last 2 hours) ===")

        # Get active users (logged in < 24 hours)
        all_active_users = get_active_users_with_ebay(hours_since_login=24)

        if not all_active_users:
            log_task("No active users to sync")
            return {
                'success': True,
                'users_processed': 0,
                'sales_created': 0,
                'sales_updated': 0
            }

        log_task(f"Found {len(all_active_users)} active users total")

        # Get current batch (20 users max)
        # Uses persistent cursor so each execution processes the next batch
        batch_users = get_user_batch(all_active_users, batch_size=20, cursor_key='sync_sold_orders_batch_cursor')
        log_task(f"Processing batch of {len(batch_users)} users")

        total_created = 0
        total_updated = 0
        users_processed = 0

        for user, credential in batch_users:
            try:
                log_task(f"  Syncing sales for user {user.id} ({user.username})...")

                # Fetch sold orders from last 2 hours only (quick sync)
                result = fetch_ebay_sold_orders(user.id, days_back=0.083)  # 2 hours = 0.083 days
                
                if not result['success']:
                    log_task(f"    ✗ Failed to fetch sold orders: {result.get('error')}")
                    continue
                
                sold_orders = result['orders']
                
                if not sold_orders:
                    log_task(f"    No new sales")
                    continue
                
                created_count = 0
                updated_count = 0
                
                for order in sold_orders:
                    # Check if sale already exists
                    existing_sale = Sale.query.filter_by(
                        user_id=user.id,
                        marketplace_order_id=order.get('marketplace_order_id')
                    ).first()

                    # SOFT DELETE: Look up item by ebay_listing_id to get item_cost and mark as sold
                    ebay_listing_id = order.get('ebay_listing_id')
                    item = None
                    item_cost = None

                    if ebay_listing_id:
                        item = Item.query.filter_by(
                            user_id=user.id,
                            ebay_listing_id=ebay_listing_id
                        ).first()

                        if item:
                            # Snapshot item cost for profit calculation
                            item_cost = item.item_cost

                            # Mark item as sold (soft delete) if not already marked
                            if not item.sold_at:
                                item.is_active = False
                                item.sold_at = order.get('sold_at')
                                item.sold_price = order.get('sold_price')
                                log_task(f"      Marked item {item.sku} as sold (soft delete)")
                                try:
                                    from qventory.helpers.link_bio import remove_featured_items_for_user
                                    remove_featured_items_for_user(user.id, [item.id])
                                except Exception:
                                    pass

                    if existing_sale:
                        # Update existing sale
                        if order.get('sold_price'):
                            existing_sale.sold_price = order['sold_price']
                        if order.get('marketplace_fee'):
                            existing_sale.marketplace_fee = order['marketplace_fee']
                        if order.get('payment_processing_fee'):
                            existing_sale.payment_processing_fee = order['payment_processing_fee']
                        if order.get('tax_collected') is not None:
                            existing_sale.tax_collected = order['tax_collected']
                        if order.get('shipping_charged') is not None:
                            existing_sale.shipping_charged = order['shipping_charged']

                        # Update item_cost if we found it
                        if item_cost is not None and existing_sale.item_cost is None:
                            existing_sale.item_cost = item_cost

                        existing_sale.updated_at = datetime.utcnow()
                        existing_sale.calculate_profit()
                        updated_count += 1
                    else:
                        # Create new sale with item_cost snapshot
                        order_data = order.copy()
                        if item_cost is not None:
                            order_data['item_cost'] = item_cost

                        # Set item_id if we found the item
                        if item:
                            order_data['item_id'] = item.id

                        new_sale = Sale(
                            user_id=user.id,
                            **order_data
                        )
                        new_sale.calculate_profit()
                        db.session.add(new_sale)
                        created_count += 1
                
                db.session.commit()
                
                log_task(f"    ✓ {created_count} created, {updated_count} updated")
                total_created += created_count
                total_updated += updated_count
                users_processed += 1

                if created_count > 0 or updated_count > 0:
                    try:
                        reconcile_sales_from_finances(
                            user_id=user.id,
                            days_back=1,
                            fetch_taxes=True,
                            force_recalculate=True
                        )
                        log_task("    ↻ Reconciled sales (last 24h)")
                    except Exception as reconcile_error:
                        log_task(f"    ⚠ Reconcile failed: {reconcile_error}")
                
            except Exception as e:
                log_task(f"    ✗ Error syncing sales for user {user.id}: {str(e)}")
                db.session.rollback()
                continue
        
        log_task(f"=== Quick-sync complete: {users_processed} users, {total_created} created, {total_updated} updated ===")

        return {
            'success': True,
            'users_processed': users_processed,
            'sales_created': total_created,
            'sales_updated': total_updated
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_sold_orders_deep')
def sync_ebay_sold_orders_deep(self):
    """
    Deep-sync sold orders for ALL users (DAILY CATCH-UP)

    Fetches sold orders from last 7 days to catch any sales that were missed
    by the quick-sync (e.g., older sales, downtime, missed syncs).

    Runs: Daily at 3:30 AM UTC
    Batch: ALL users with eBay connected (no batching, runs once daily)
    API Calls: ~100-200 per execution (depending on user count)
    Range: Last 7 days (comprehensive catch-up)

    This ensures no sales are permanently missed even if:
    - Quick-sync had downtime
    - Sales were older when first created
    - User was offline when sale happened

    Returns:
        dict: Summary of sync operations
    """
    app = create_app()

    with app.app_context():
        from qventory.helpers.ebay_inventory import fetch_ebay_sold_orders
        from qventory.models.sale import Sale
        from qventory.models.item import Item
        from qventory.models.user import User
        from qventory.models.marketplace_credential import MarketplaceCredential
        from datetime import datetime

        log_task("=== Deep-sync sold orders (last 7 days) - DAILY CATCH-UP ===")

        # Get ALL users with eBay connected (no activity filter for deep sync)
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No users with eBay connected")
            return {
                'success': True,
                'users_processed': 0,
                'sales_created': 0,
                'sales_updated': 0
            }

        users_with_ebay = []
        for cred in credentials:
            user = User.query.get(cred.user_id)
            if user:
                users_with_ebay.append((user, cred))

        log_task(f"Found {len(users_with_ebay)} users with eBay connected")

        total_created = 0
        total_updated = 0
        users_processed = 0
        users_with_sales = 0

        for user, credential in users_with_ebay:
            try:
                log_task(f"  Deep-syncing sales for user {user.id} ({user.username})...")

                # Fetch sold orders from last 7 days (comprehensive catch-up)
                result = fetch_ebay_sold_orders(user.id, days_back=7)

                if not result['success']:
                    log_task(f"    ✗ Failed to fetch sold orders: {result.get('error')}")
                    continue

                sold_orders = result['orders']

                if not sold_orders:
                    log_task(f"    No sales found")
                    continue

                created_count = 0
                updated_count = 0

                for order in sold_orders:
                    # Check if sale already exists
                    existing_sale = Sale.query.filter_by(
                        user_id=user.id,
                        marketplace_order_id=order.get('marketplace_order_id')
                    ).first()

                    # SOFT DELETE: Look up item by ebay_listing_id to get item_cost and mark as sold
                    ebay_listing_id = order.get('ebay_listing_id')
                    item = None
                    item_cost = None

                    if ebay_listing_id:
                        item = Item.query.filter_by(
                            user_id=user.id,
                            ebay_listing_id=ebay_listing_id
                        ).first()

                        if item:
                            # Snapshot item cost for profit calculation
                            item_cost = item.item_cost

                            # Mark item as sold (soft delete) if not already marked
                            if not item.sold_at:
                                item.is_active = False
                                item.sold_at = order.get('sold_at')
                                item.sold_price = order.get('sold_price')
                                log_task(f"      Marked item {item.sku} as sold (soft delete)")

                    if existing_sale:
                        # Update existing sale (in case data changed)
                        if order.get('sold_price'):
                            existing_sale.sold_price = order.get('sold_price')
                        if order.get('marketplace_fee') is not None:
                            existing_sale.marketplace_fee = order.get('marketplace_fee')
                        if order.get('payment_processing_fee') is not None:
                            existing_sale.payment_processing_fee = order.get('payment_processing_fee')
                        if order.get('other_fees') is not None:
                            existing_sale.other_fees = order.get('other_fees')
                        if order.get('tax_collected') is not None:
                            existing_sale.tax_collected = order.get('tax_collected')
                        if order.get('shipping_charged') is not None:
                            existing_sale.shipping_charged = order.get('shipping_charged')
                        if order.get('shipped_at'):
                            existing_sale.shipped_at = order.get('shipped_at')
                        if order.get('delivered_at'):
                            existing_sale.delivered_at = order.get('delivered_at')
                        if order.get('status'):
                            existing_sale.status = order.get('status')

                        # Update item_cost if we found it and it wasn't set before
                        if item_cost is not None and existing_sale.item_cost is None:
                            existing_sale.item_cost = item_cost

                        # Recalculate profit and update timestamp (consistency with quick sync)
                        existing_sale.updated_at = datetime.utcnow()
                        existing_sale.calculate_profit()
                        updated_count += 1
                    else:
                        # Create new sale record
                        sold_price = order.get('sold_price', 0)
                        marketplace_fee = order.get('marketplace_fee')
                        payment_fee = order.get('payment_processing_fee')
                        shipping_cost = order.get('shipping_cost', 0)
                        other_fees = order.get('other_fees')

                        if marketplace_fee is None:
                            marketplace_fee = sold_price * 0.1325  # ~13.25% eBay final value fee
                        if payment_fee is None:
                            payment_fee = sold_price * 0.029 + 0.30  # Payment processing

                        new_sale = Sale(
                            user_id=user.id,
                            item_id=item.id if item else None,
                            item_title=order.get('item_title'),
                            item_sku=order.get('item_sku'),
                            item_cost=item_cost,
                            sold_price=sold_price,
                            tax_collected=order.get('tax_collected'),
                            marketplace=order.get('marketplace', 'ebay'),
                            marketplace_order_id=order.get('marketplace_order_id'),
                            marketplace_fee=marketplace_fee,
                            payment_processing_fee=payment_fee,
                            shipping_cost=shipping_cost,
                            shipping_charged=order.get('shipping_charged'),
                            other_fees=other_fees,
                            sold_at=order.get('sold_at', datetime.utcnow()),
                            shipped_at=order.get('shipped_at'),
                            delivered_at=order.get('delivered_at'),
                            status=order.get('status', 'paid')
                        )

                        # Use calculate_profit() method for consistency with other sync tasks
                        new_sale.calculate_profit()
                        db.session.add(new_sale)
                        created_count += 1

                db.session.commit()

                if created_count > 0 or updated_count > 0:
                    log_task(f"    ✓ {created_count} created, {updated_count} updated")
                    users_with_sales += 1
                    try:
                        reconcile_sales_from_finances(
                            user_id=user.id,
                            days_back=7,
                            fetch_taxes=True,
                            force_recalculate=True
                        )
                        log_task("    ↻ Reconciled sales (7 days)")
                    except Exception as reconcile_error:
                        log_task(f"    ⚠ Reconcile failed: {reconcile_error}")

                total_created += created_count
                total_updated += updated_count
                users_processed += 1

            except Exception as e:
                log_task(f"    ✗ Error deep-syncing sales for user {user.id}: {str(e)}")
                db.session.rollback()
                continue

        log_task(f"=== Deep-sync complete: {users_processed} users processed, {users_with_sales} had sales, {total_created} created, {total_updated} updated ===")

        return {
            'success': True,
            'users_processed': users_processed,
            'users_with_sales': users_with_sales,
            'sales_created': total_created,
            'sales_updated': total_updated
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_fulfillment_tracking_global')
def sync_ebay_fulfillment_tracking_global(self):
    """
    Refresh fulfillment tracking for all active eBay accounts.
    Runs on a schedule to keep delivered statuses updated.
    """
    app = create_app()

    with app.app_context():
        from qventory.helpers.fulfillment_sync import sync_fulfillment_orders
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User

        log_task("=== Fulfillment tracking global sync ===")

        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No active eBay accounts found")
            return {
                'success': True,
                'users_processed': 0,
                'orders_synced': 0
            }

        total_synced = 0
        users_processed = 0

        for cred in credentials:
            user = User.query.get(cred.user_id)
            if not user:
                continue
            try:
                log_task(f"  Syncing fulfillment for user {user.id} ({user.username})")
                result = sync_fulfillment_orders(user.id, limit=800)
                if result.get('success'):
                    total_synced += result.get('orders_synced', 0)
                    users_processed += 1
                else:
                    log_task(f"    ✗ Failed: {result.get('error')}")
            except Exception as exc:
                log_task(f"    ✗ Error syncing user {user.id}: {exc}")
                db.session.rollback()
                continue

        log_task(f"=== Fulfillment tracking sync complete: {users_processed} users, {total_synced} orders synced ===")

        return {
            'success': True,
            'users_processed': users_processed,
            'orders_synced': total_synced
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_fulfillment_tracking_user')
def sync_ebay_fulfillment_tracking_user(self, user_id):
    """
    Refresh fulfillment tracking for a single user (manual sync).
    """
    app = create_app()

    with app.app_context():
        from qventory.helpers.fulfillment_sync import sync_fulfillment_orders

        try:
            return sync_fulfillment_orders(user_id, limit=800)
        except Exception as exc:
            log_task(f"Fulfillment sync failed for user {user_id}: {exc}")
            return {
                'success': False,
                'error': str(exc),
                'orders_synced': 0,
                'orders_created': 0,
                'orders_updated': 0
            }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_finances_user')
def sync_ebay_finances_user(self, user_id, days_back=120):
    app = create_app()
    with app.app_context():
        from qventory.models.ebay_finance import EbayPayout, EbayFinanceTransaction
        from qventory.helpers.ebay_finances import (
            fetch_all_ebay_payouts,
            fetch_all_ebay_transactions
        )

        log_task(f"=== Syncing eBay finances for user {user_id} ===")
        if days_back is None:
            start_date = datetime.utcnow() - timedelta(days=1825)  # eBay max: 5 years
        else:
            start_date = datetime.utcnow() - timedelta(days=min(days_back, 1825))
        end_date = datetime.utcnow()

        payouts_result = fetch_all_ebay_payouts(user_id, start_date, end_date, limit=200)
        if not payouts_result.get('success'):
            return {'success': False, 'error': payouts_result.get('error')}

        transactions_result = fetch_all_ebay_transactions(user_id, start_date, end_date, limit=200)
        if not transactions_result.get('success'):
            return {'success': False, 'error': transactions_result.get('error')}

        payouts_created = 0
        payouts_updated = 0
        for payout in payouts_result.get('payouts', []):
            payout_id = payout.get('payoutId') or payout.get('payout_id')
            payout_date = _parse_ebay_datetime(
                payout.get('payoutDate') or payout.get('payoutDateTime') or payout.get('payoutDateTimeGMT')
            )
            status = payout.get('payoutStatus') or payout.get('status')
            amount = payout.get('amount') or payout.get('payoutAmount') or {}
            fee = payout.get('payoutFee') or payout.get('fee') or {}
            currency = amount.get('currency') or fee.get('currency')
            gross_value = float(amount.get('value', 0) or 0)
            fee_value = float(fee.get('value', 0) or 0)
            net_value = gross_value - fee_value

            external_id = payout_id or _build_external_id(
                "payout",
                [payout_date, gross_value, fee_value, status]
            )

            existing = EbayPayout.query.filter_by(
                user_id=user_id,
                external_id=external_id
            ).first()
            if existing:
                record = existing
                payouts_updated += 1
            else:
                record = EbayPayout(user_id=user_id, external_id=external_id)
                payouts_created += 1

            record.payout_id = payout_id
            record.payout_date = payout_date
            record.status = status
            record.gross_amount = gross_value
            record.fee_amount = fee_value
            record.net_amount = net_value
            record.currency = currency
            record.raw_json = payout
            db.session.add(record)

        tx_created = 0
        tx_updated = 0
        for txn in transactions_result.get('transactions', []):
            txn_id = txn.get('transactionId') or txn.get('adjustmentId')
            txn_date = _parse_ebay_datetime(
                txn.get('transactionDate') or txn.get('creationDate')
            )
            txn_type = (txn.get('transactionType') or txn.get('type') or '').upper()
            amount = txn.get('amount') or {}
            currency = amount.get('currency')
            value = float(amount.get('value', 0) or 0)
            order_id = txn.get('orderId')
            reference_id = txn.get('referenceId')
            ref_order_ids, ref_line_ids, ref_all_ids = extract_finance_reference_ids(txn)
            if not order_id and ref_order_ids:
                order_id = next(iter(ref_order_ids))
            if not reference_id and ref_all_ids:
                reference_id = next(iter(ref_all_ids))

            external_id = txn_id or _build_external_id(
                "txn",
                [txn_date, txn_type, value, order_id, reference_id]
            )

            existing = EbayFinanceTransaction.query.filter_by(
                user_id=user_id,
                external_id=external_id
            ).first()
            if existing:
                record = existing
                tx_updated += 1
            else:
                record = EbayFinanceTransaction(user_id=user_id, external_id=external_id)
                tx_created += 1

            record.transaction_id = txn_id
            record.transaction_date = txn_date
            record.transaction_type = txn_type
            record.amount = value
            record.currency = currency
            record.order_id = order_id
            record.reference_id = reference_id
            record.raw_json = txn
            db.session.add(record)

        db.session.commit()
        log_task(
            f"eBay finances sync complete: payouts +{payouts_created}/~{payouts_updated}, "
            f"transactions +{tx_created}/~{tx_updated}"
        )
        return {
            'success': True,
            'payouts_created': payouts_created,
            'payouts_updated': payouts_updated,
            'transactions_created': tx_created,
            'transactions_updated': tx_updated
        }


def extract_finance_reference_ids(txn_raw):
    order_ids = set()
    line_item_ids = set()
    reference_ids = set()

    if txn_raw.get('orderId'):
        order_ids.add(txn_raw.get('orderId'))
        reference_ids.add(txn_raw.get('orderId'))
    if txn_raw.get('referenceId'):
        reference_ids.add(txn_raw.get('referenceId'))

    references = txn_raw.get('references') or []
    for ref in references:
        ref_id = ref.get('referenceId') or ref.get('refId') or ref.get('id')
        ref_type = (ref.get('referenceType') or ref.get('type') or '').upper()
        if not ref_id:
            continue
        reference_ids.add(ref_id)
        if 'ORDER' in ref_type:
            order_ids.add(ref_id)
        if 'LINE' in ref_type or 'ITEM' in ref_type or 'TRANSACTION' in ref_type:
            line_item_ids.add(ref_id)

    return order_ids, line_item_ids, reference_ids


def classify_finance_fee(txn_raw, amount):
    fee_type = (
        txn_raw.get('feeType')
        or txn_raw.get('feeTypeCode')
        or txn_raw.get('feeTypeEnum')
        or ''
    )
    fee_type = str(fee_type).upper()
    transaction_type = str(txn_raw.get('transactionType') or txn_raw.get('type') or '').upper()
    reference_types = {
        (ref.get('referenceType') or ref.get('type') or '').upper()
        for ref in (txn_raw.get('references') or [])
    }

    if not amount:
        return None

    # Shipping label: detect by transactionType first (eBay Finances API
    # returns SHIPPING_LABEL as a separate transaction type)
    if transaction_type == 'SHIPPING_LABEL':
        return 'shipping_label'

    if 'PAYMENT_PROCESSING' in fee_type:
        return 'payment_processing'
    if 'FINAL_VALUE' in fee_type or 'MARKETPLACE' in fee_type:
        return 'marketplace'
    if 'SHIPPING' in fee_type and 'LABEL' in fee_type:
        return 'shipping_label'
    if any('SHIPPING_LABEL' in ref_type for ref_type in reference_types):
        return 'shipping_label'
    if 'AD_FEE' in fee_type or 'ADVERTISING' in fee_type or 'PROMOTED' in fee_type:
        return 'ad_fee'
    if 'INTERNATIONAL' in fee_type or 'REGULATORY' in fee_type:
        return 'other'
    if transaction_type in {'NON_SALE_CHARGE', 'FEE', 'ADJUSTMENT', 'REFUND', 'DISPUTE'}:
        return 'other'
    if amount < 0:
        return 'other'

    return None


def _classify_marketplace_fee_type(fee_type_str):
    """Classify an individual marketplaceFees entry feeType from Finances API."""
    ft = str(fee_type_str or '').upper()
    if 'FINAL_VALUE' in ft:
        return 'marketplace'
    if 'AD_FEE' in ft or 'ADVERTISING' in ft or 'PROMOTED' in ft:
        return 'ad_fee'
    if 'INTERNATIONAL' in ft or 'REGULATORY' in ft:
        return 'other'
    return 'marketplace'


def extract_granular_fees_from_transaction(txn_raw):
    """
    Extract granular per-fee-type totals from a Finances API SALE transaction.

    The Finances API returns orderLineItems[].marketplaceFees[] with individual
    fee entries (FINAL_VALUE_FEE, AD_FEE, etc.) plus totalFeeAmount for the
    transaction total.

    Returns a dict: {marketplace, ad_fee, payment_processing, shipping_label, other}
    or None if no granular data is available.
    """
    order_line_items = txn_raw.get('orderLineItems') or []
    if not order_line_items:
        return None

    fees = {
        'marketplace': 0.0,
        'ad_fee': 0.0,
        'payment_processing': 0.0,
        'shipping_label': 0.0,
        'other': 0.0
    }

    found_any = False
    for li in order_line_items:
        marketplace_fees = li.get('marketplaceFees') or []
        for mf in marketplace_fees:
            fee_amount_obj = mf.get('amount') or {}
            try:
                fee_val = abs(float(fee_amount_obj.get('value', 0) or 0))
            except (TypeError, ValueError):
                continue
            if fee_val == 0:
                continue

            fee_type = mf.get('feeType') or ''
            bucket = _classify_marketplace_fee_type(fee_type)
            fees[bucket] += fee_val
            found_any = True

    return fees if found_any else None


def reconcile_sales_from_finances(*, user_id, days_back=None, fetch_taxes=False, force_recalculate=False, skip_fulfillment_api=False, only_missing=False):
    from qventory.models.sale import Sale
    from qventory.models.ebay_finance import EbayFinanceTransaction
    from qventory.helpers.ebay_inventory import (
        fetch_ebay_order_details,
        parse_ebay_order_to_sale,
        fetch_trading_order_fees
    )

    start_date = None
    if days_back is not None:
        try:
            days_back = int(days_back)
        except (TypeError, ValueError):
            days_back = None
    if days_back:
        start_date = datetime.utcnow() - timedelta(days=days_back)

    sales_query = Sale.query.filter_by(user_id=user_id)
    if start_date is not None:
        sales_query = sales_query.filter(Sale.sold_at >= start_date)
    sales = sales_query.all()

    tx_query = EbayFinanceTransaction.query.filter_by(user_id=user_id)
    if start_date is not None:
        tx_query = tx_query.filter(EbayFinanceTransaction.transaction_date >= start_date)
    transactions = tx_query.all()
    has_finances = len(transactions) > 0

    totals_by_order = {}
    totals_by_line_item = {}
    trading_fee_cache = {}
    order_detail_cache = {}
    parsed_order_cache = {}

    EMPTY_FEES = {
        'marketplace': 0.0,
        'ad_fee': 0.0,
        'payment_processing': 0.0,
        'other': 0.0,
        'shipping_label': 0.0,
        'refund': 0.0
    }

    for txn in transactions:
        raw = txn.raw_json or {}
        amount = float(txn.amount or 0)
        transaction_type = str(raw.get('transactionType') or raw.get('type') or '').upper()

        order_ids, line_item_ids, reference_ids = extract_finance_reference_ids(raw)
        if txn.order_id:
            order_ids.add(txn.order_id)
            reference_ids.add(txn.order_id)
        if txn.reference_id:
            reference_ids.add(txn.reference_id)

        target_order_ids = order_ids or set()
        target_line_ids = line_item_ids or set()

        # REFUND transactions — track refund amount per order
        if transaction_type == 'REFUND':
            value = abs(amount)
            for order_id in target_order_ids:
                totals = totals_by_order.setdefault(order_id, dict(EMPTY_FEES))
                totals['refund'] += value
            for line_id in target_line_ids:
                totals = totals_by_line_item.setdefault(line_id, dict(EMPTY_FEES))
                totals['refund'] += value
            continue

        # For SALE transactions, try to extract granular per-fee breakdown
        # from orderLineItems.marketplaceFees
        if transaction_type == 'SALE':
            granular = extract_granular_fees_from_transaction(raw)
            if granular:
                for order_id in target_order_ids:
                    totals = totals_by_order.setdefault(order_id, dict(EMPTY_FEES))
                    for bucket, val in granular.items():
                        totals[bucket] += val
                for line_id in target_line_ids:
                    totals = totals_by_line_item.setdefault(line_id, dict(EMPTY_FEES))
                    for bucket, val in granular.items():
                        totals[bucket] += val
                continue  # Skip the legacy classify path for this transaction

        # Fallback: classify entire transaction amount by feeType/transactionType
        fee_bucket = classify_finance_fee(raw, amount)
        if not fee_bucket:
            continue
        value = abs(amount)

        for order_id in target_order_ids:
            totals = totals_by_order.setdefault(order_id, dict(EMPTY_FEES))
            totals[fee_bucket] += value

        for line_id in target_line_ids:
            totals = totals_by_line_item.setdefault(line_id, dict(EMPTY_FEES))
            totals[fee_bucket] += value

    updated = 0
    taxes_updated = 0
    for sale in sales:
        updated_this_sale = False
        fees = None
        if sale.marketplace_order_id and sale.marketplace_order_id in totals_by_order:
            fees = totals_by_order[sale.marketplace_order_id]
        elif sale.ebay_transaction_id and sale.ebay_transaction_id in totals_by_line_item:
            fees = totals_by_line_item[sale.ebay_transaction_id]

        if fees:
            # In only_missing mode, skip sales that already have fees populated
            if only_missing and (sale.shipping_cost or 0) > 0 and (sale.marketplace_fee or 0) > 0:
                if force_recalculate:
                    sale.calculate_profit()
                continue

            sale.marketplace_fee = fees['marketplace']
            sale.payment_processing_fee = fees['payment_processing']
            sale.ad_fee = fees['ad_fee']
            sale.other_fees = fees['other']
            sale.shipping_cost = fees['shipping_label']
            if fees['refund'] > 0:
                sale.refund_amount = fees['refund']
                if sale.status not in ('cancelled',):
                    sale.status = 'refunded'
            updated += 1
            updated_this_sale = True
        elif not has_finances and not skip_fulfillment_api:
            parsed = None
            if sale.marketplace_order_id:
                parsed = parsed_order_cache.get(sale.marketplace_order_id)
                if parsed is None:
                    order_detail = order_detail_cache.get(sale.marketplace_order_id)
                    if order_detail is None:
                        order_detail = fetch_ebay_order_details(user_id, sale.marketplace_order_id)
                        order_detail_cache[sale.marketplace_order_id] = order_detail
                    if order_detail:
                        parsed = parse_ebay_order_to_sale(order_detail, user_id=user_id)
                        parsed_order_cache[sale.marketplace_order_id] = parsed

            marketplace_fee_value = None
            if parsed and parsed.get('marketplace_fee') is not None:
                marketplace_fee_value = parsed.get('marketplace_fee')

            if marketplace_fee_value is not None:
                if sale.marketplace_fee != marketplace_fee_value:
                    sale.marketplace_fee = marketplace_fee_value
                    updated_this_sale = True
            elif sale.marketplace_order_id:
                # Trading API fallback disabled to avoid rate limits.
                pass

            shipping_charged = sale.shipping_charged or 0
            if (sale.shipping_cost or 0) == 0 and shipping_charged > 0:
                # Fallback: use buyer-paid shipping as estimated label cost
                sale.shipping_cost = shipping_charged
                updated_this_sale = True

        if fetch_taxes and not skip_fulfillment_api and (sale.tax_collected is None or sale.tax_collected == 0) and sale.marketplace_order_id:
            parsed = parsed_order_cache.get(sale.marketplace_order_id)
            if parsed is None:
                order_detail = order_detail_cache.get(sale.marketplace_order_id)
                if order_detail is None:
                    order_detail = fetch_ebay_order_details(user_id, sale.marketplace_order_id)
                    order_detail_cache[sale.marketplace_order_id] = order_detail
                if order_detail:
                    parsed = parse_ebay_order_to_sale(order_detail, user_id=user_id)
                    parsed_order_cache[sale.marketplace_order_id] = parsed

            if parsed and parsed.get('tax_collected') is not None:
                sale.tax_collected = parsed.get('tax_collected')
                taxes_updated += 1
                updated_this_sale = True

        # Sync refund info from Fulfillment API if not already set by Finances API
        if not skip_fulfillment_api and not sale.refund_amount and sale.marketplace_order_id:
            parsed = parsed_order_cache.get(sale.marketplace_order_id)
            if parsed is None:
                order_detail = order_detail_cache.get(sale.marketplace_order_id)
                if order_detail is None:
                    order_detail = fetch_ebay_order_details(user_id, sale.marketplace_order_id)
                    order_detail_cache[sale.marketplace_order_id] = order_detail
                if order_detail:
                    parsed = parse_ebay_order_to_sale(order_detail, user_id=user_id)
                    parsed_order_cache[sale.marketplace_order_id] = parsed

            if parsed and parsed.get('refund_amount'):
                sale.refund_amount = parsed['refund_amount']
                sale.refund_reason = parsed.get('refund_reason')
                if sale.status not in ('cancelled',):
                    sale.status = 'refunded'
                updated_this_sale = True

        if updated_this_sale or force_recalculate:
            sale.calculate_profit()

    db.session.commit()

    return {
        'success': True,
        'updated_sales': updated,
        'taxes_updated': taxes_updated
    }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_finances_global')
def sync_ebay_finances_global(self):
    app = create_app()
    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User

        log_task("=== Global eBay finances sync ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No active eBay accounts found")
            return {'success': True, 'users_processed': 0, 'errors': 0}

        users_processed = 0
        errors = 0
        for cred in credentials:
            user = User.query.get(cred.user_id)
            if not user:
                continue
            try:
                users_processed += 1
                sync_ebay_finances_user.run(cred.user_id)
            except Exception as exc:
                errors += 1
                log_task(f"Finance sync failed for user {cred.user_id}: {exc}")

        log_task(
            f"=== Global finances sync complete: {users_processed} users, {errors} errors ==="
        )
        return {'success': True, 'users_processed': users_processed, 'errors': errors}


@celery.task(bind=True, name='qventory.tasks.recalculate_ebay_analytics_global')
def recalculate_ebay_analytics_global(self):
    app = create_app()
    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User

        log_task("=== Global analytics recalculation ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No active eBay accounts found")
            return {'success': True, 'users_processed': 0, 'errors': 0}

        import time

        users_processed = 0
        errors = 0
        for i, cred in enumerate(credentials):
            user = User.query.get(cred.user_id)
            if not user:
                continue

            # Rate limit: wait between users to avoid eBay 429s
            if i > 0:
                time.sleep(10)

            try:
                users_processed += 1
                log_task(f"Recalculating analytics for user {cred.user_id} ({user.username})... [{users_processed}/{len(credentials)}]")

                import_ebay_sales.run(cred.user_id, days_back=730)
                time.sleep(2)

                sync_ebay_finances_user.run(cred.user_id, days_back=730)
                time.sleep(2)

                reconcile_sales_from_finances(
                    user_id=cred.user_id,
                    days_back=730,
                    fetch_taxes=True,
                    force_recalculate=True
                )

                log_task(f"Analytics recalculation complete for user {cred.user_id}")
            except Exception as exc:
                errors += 1
                log_task(f"Analytics recalculation failed for user {cred.user_id}: {exc}")

        log_task(
            f"=== Global analytics recalculation complete: {users_processed} users, {errors} errors ==="
        )
        return {'success': True, 'users_processed': users_processed, 'errors': errors}


@celery.task(bind=True, name='qventory.tasks.reconcile_user_finances')
def reconcile_user_finances(self, user_id):
    """Reconcile finances + shipping costs for a single user."""
    app = create_app()
    with app.app_context():
        from qventory.models.user import User

        user = User.query.get(user_id)
        username = user.username if user else f"ID {user_id}"
        log_task(f"=== Reconciling finances for user {user_id} ({username}) ===")

        try:
            sync_ebay_finances_user.run(user_id, days_back=730)
            log_task(f"Finance sync complete for user {user_id}")
        except Exception as exc:
            log_task(f"Finance sync failed for user {user_id}: {exc}")
            return {'success': False, 'error': str(exc)}

        try:
            result = reconcile_sales_from_finances(
                user_id=user_id,
                days_back=730,
                fetch_taxes=False,
                force_recalculate=True,
                skip_fulfillment_api=True
            )
            log_task(f"Reconciliation complete for user {user_id}: {result}")
            return {'success': True, 'result': result}
        except Exception as exc:
            log_task(f"Reconciliation failed for user {user_id}: {exc}")
            return {'success': False, 'error': str(exc)}


@celery.task(bind=True, name='qventory.tasks.backfill_shipping_costs_global')
def backfill_shipping_costs_global(self):
    """
    Lightweight global task: sync finances + reconcile to populate shipping label
    costs (and other fees) for all eBay-connected users.
    Skips import_ebay_sales to avoid heavy Fulfillment API calls.
    Adds a 5-second delay between users to avoid 429 rate limits.
    """
    import time
    app = create_app()
    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User

        log_task("=== Global shipping cost backfill ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        if not credentials:
            log_task("No active eBay accounts found")
            return {'success': True, 'users_processed': 0, 'errors': 0}

        users_processed = 0
        errors = 0
        for i, cred in enumerate(credentials):
            user = User.query.get(cred.user_id)
            if not user:
                continue

            # Rate limit: wait between users (skip delay before first user)
            if i > 0:
                time.sleep(5)

            try:
                users_processed += 1
                log_task(f"Backfilling shipping costs for user {cred.user_id} ({user.username})...")

                # Step 1: Sync finances (fetches SHIPPING_LABEL transactions from Finances API)
                sync_ebay_finances_user.run(cred.user_id, days_back=730)

                # Step 2: Reconcile to map fees (including shipping_label) to sales
                # skip_fulfillment_api=True to avoid 429 rate limits from Fulfillment API
                reconcile_sales_from_finances(
                    user_id=cred.user_id,
                    days_back=730,
                    fetch_taxes=False,
                    force_recalculate=True,
                    skip_fulfillment_api=True
                )

                log_task(f"Shipping cost backfill complete for user {cred.user_id}")
            except Exception as exc:
                errors += 1
                log_task(f"Shipping cost backfill failed for user {cred.user_id}: {exc}")

        log_task(
            f"=== Global shipping cost backfill complete: {users_processed} users, {errors} errors ==="
        )
        return {'success': True, 'users_processed': users_processed, 'errors': errors}


@celery.task(bind=True, name='qventory.tasks.process_recurring_expenses')
def process_recurring_expenses(self):
    """
    Process recurring expenses - creates new expense entries for active recurring expenses
    Should be run daily via cron/celerybeat
    """
    app = create_app()

    with app.app_context():
        from qventory.models.expense import Expense
        from qventory.models.item import Item
        from datetime import date, datetime
        from dateutil.relativedelta import relativedelta

        log_task("=== Processing recurring expenses ===")

        import calendar
        today = date.today()
        current_day = today.day
        last_day_of_month = calendar.monthrange(today.year, today.month)[1]

        # Find all active recurring expenses
        recurring_expenses = Expense.query.filter(
            Expense.is_recurring == True
        ).all()

        log_task(f"Found {len(recurring_expenses)} recurring expenses to check")

        created_count = 0

        for expense in recurring_expenses:
            # Skip if not active
            if not expense.is_active_recurring:
                continue

            # Check if we should create an expense today
            should_create = False

            if expense.recurring_frequency == 'monthly':
                recurring_day = expense.recurring_day or expense.expense_date.day
                target_day = min(recurring_day, last_day_of_month)

                # If today is the target day, create it
                if target_day == current_day:
                    should_create = True
                # Catch-up: if we've passed the target day this month and it's missing, create now
                elif current_day > target_day:
                    should_create = True
            elif expense.recurring_frequency == 'weekly':
                recurring_day = expense.recurring_day
                if recurring_day is None:
                    recurring_day = expense.expense_date.weekday()
                # Check if today's weekday matches
                if today.weekday() == recurring_day:
                    should_create = True
            elif expense.recurring_frequency == 'yearly':
                # Check if today matches month/day of original expense
                if (expense.expense_date.month == today.month and
                    expense.expense_date.day == current_day):
                    should_create = True

            if not should_create:
                continue

            # For monthly recurring, avoid duplicates if one already exists this month
            if expense.recurring_frequency == 'monthly':
                month_start = today.replace(day=1)
                next_month = (month_start + relativedelta(months=1))
                existing_month = Expense.query.filter(
                    Expense.user_id == expense.user_id,
                    Expense.description == expense.description,
                    Expense.amount == expense.amount,
                    Expense.category == expense.category,
                    Expense.item_id == expense.item_id,
                    Expense.expense_date >= month_start,
                    Expense.expense_date < next_month
                ).first()
                if existing_month:
                    log_task(
                        f"  Skipping {expense.description} for user {expense.user_id} - already exists this month"
                    )
                    continue

            # Check if we already created this expense today (avoid duplicates)
            existing = Expense.query.filter(
                Expense.user_id == expense.user_id,
                Expense.description == expense.description,
                Expense.amount == expense.amount,
                Expense.expense_date == today,
                Expense.category == expense.category,
                Expense.item_id == expense.item_id
            ).first()

            if existing:
                log_task(f"  Skipping {expense.description} for user {expense.user_id} - already exists for today")
                continue

            # Create new expense entry
            new_expense = Expense(
                user_id=expense.user_id,
                description=expense.description,
                amount=expense.amount,
                category=expense.category,
                expense_date=today,
                is_recurring=False,  # The copy is not recurring itself
                notes=f"Auto-created from recurring expense #{expense.id}",
                item_id=expense.item_id
            )

            if new_expense.item_id:
                linked_item = Item.query.get(new_expense.item_id)
                if linked_item:
                    linked_item.item_cost = (linked_item.item_cost or 0) + new_expense.amount
                    new_expense.item_cost_applied = True
                    new_expense.item_cost_applied_amount = new_expense.amount
                    new_expense.item_cost_applied_at = datetime.utcnow()

            db.session.add(new_expense)
            created_count += 1
            log_task(f"  ✓ Created {expense.description} (${expense.amount}) for user {expense.user_id}")

        db.session.commit()

        log_task(f"=== Recurring expenses complete: {created_count} expenses created ===")

        return {
            'success': True,
            'created': created_count,
            'total_checked': len(recurring_expenses)
        }


@celery.task(bind=True, name='qventory.tasks.revive_recurring_expenses')
def revive_recurring_expenses(self):
    """
    Create current-month entries for users who had recurring expenses last month.
    Useful for recovery if recurring jobs did not run.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.expense import Expense
        from qventory.models.item import Item
        from datetime import date
        from dateutil.relativedelta import relativedelta

        log_task("=== Reviving recurring expenses (last-month users) ===")

        today = date.today()
        month_start = today.replace(day=1)
        next_month = month_start + relativedelta(months=1)
        last_month_start = month_start - relativedelta(months=1)

        # Users who had any recurring expense activity last month
        last_month_user_ids = {
            row.user_id
            for row in Expense.query.filter(
                Expense.expense_date >= last_month_start,
                Expense.expense_date < month_start,
                (
                    Expense.is_recurring == True
                ) | (
                    Expense.notes.ilike('%recurring expense%')
                )
            ).all()
        }

        if not last_month_user_ids:
            log_task("No users with recurring expenses last month")
            return {'success': True, 'created': 0, 'users_checked': 0}

        recurring_expenses = Expense.query.filter(
            Expense.user_id.in_(last_month_user_ids),
            Expense.is_recurring == True
        ).all()

        created_count = 0
        for expense in recurring_expenses:
            if not expense.is_active_recurring:
                continue

            existing_month = Expense.query.filter(
                Expense.user_id == expense.user_id,
                Expense.description == expense.description,
                Expense.amount == expense.amount,
                Expense.category == expense.category,
                Expense.item_id == expense.item_id,
                Expense.expense_date >= month_start,
                Expense.expense_date < next_month
            ).first()
            if existing_month:
                continue

            new_expense = Expense(
                user_id=expense.user_id,
                description=expense.description,
                amount=expense.amount,
                category=expense.category,
                expense_date=today,
                is_recurring=False,
                notes=f"Auto-created (revived) from recurring expense #{expense.id}",
                item_id=expense.item_id
            )

            if new_expense.item_id:
                linked_item = Item.query.get(new_expense.item_id)
                if linked_item:
                    linked_item.item_cost = (linked_item.item_cost or 0) + new_expense.amount
                    new_expense.item_cost_applied = True
                    new_expense.item_cost_applied_amount = new_expense.amount
                    new_expense.item_cost_applied_at = datetime.utcnow()
            db.session.add(new_expense)
            created_count += 1

        db.session.commit()

        log_task(
            f"=== Revive complete: {created_count} expenses created for {len(last_month_user_ids)} users ==="
        )
        return {
            'success': True,
            'created': created_count,
            'users_checked': len(last_month_user_ids)
        }


@celery.task(bind=True, name='qventory.tasks.backfill_failed_payments')
def backfill_failed_payments(self):
    """
    Admin task: backfill failed Stripe payments and downgrade users after trial.
    """
    app = create_app()

    with app.app_context():
        import os
        import stripe
        from datetime import datetime
        from qventory.models.subscription import Subscription
        from qventory.helpers.email_sender import send_payment_failed_email
        from qventory.routes.main import _downgrade_to_free_and_enforce

        stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
        if not stripe_secret:
            return {'success': False, 'error': 'STRIPE_SECRET_KEY not configured'}

        stripe.api_key = stripe_secret

        now = datetime.utcnow()
        processed = 0
        downgraded = 0
        emails_sent = 0
        errors = 0

        subs = Subscription.query.filter(
            Subscription.stripe_subscription_id.isnot(None)
        ).all()

        for subscription in subs:
            try:
                stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
                status = stripe_sub.get("status")
                trial_end = stripe_sub.get("trial_end")
                trial_over = True
                if trial_end:
                    trial_over = datetime.utcfromtimestamp(trial_end) <= now

                if status not in {"past_due", "unpaid"} or not trial_over:
                    continue

                if subscription.plan == "free":
                    continue

                processed += 1

                if subscription.plan != "free":
                    _downgrade_to_free_and_enforce(subscription.user, subscription, now)
                    downgraded += 1
                subscription.status = "suspended"
                subscription.updated_at = now
                db.session.commit()

                try:
                    send_payment_failed_email(subscription.user.email, subscription.user.username)
                    emails_sent += 1
                except Exception:
                    pass

            except Exception:
                errors += 1

        return {
            'success': True,
            'processed': processed,
            'downgraded': downgraded,
            'emails_sent': emails_sent,
            'errors': errors
        }


@celery.task(bind=True, name='qventory.tasks.sync_and_purge_inactive_items')
def sync_and_purge_inactive_items(self):
    """
    Admin task: Sync all eBay accounts and purge items that are no longer active on eBay

    This task:
    1. Finds all users with eBay connected
    2. Syncs their eBay inventory to get current active listings
    3. Marks items as inactive if they no longer exist on eBay
    4. Optionally deletes items that have been inactive for too long

    Returns:
        dict with sync and purge results
    """
    app = create_app()

    with app.app_context():
        from qventory.models.user import User
        from qventory.models.item import Item
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.helpers.ebay_inventory import fetch_active_listings_snapshot
        from sqlalchemy import and_

        log_task("=== ADMIN: Starting eBay sync and purge task ===")

        # Find all users with active eBay credentials
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        log_task(f"Found {len(credentials)} active eBay credentials")

        total_synced = 0
        total_marked_inactive = 0
        total_purged = 0
        users_processed = 0

        for cred in credentials:
            try:
                user = cred.owner or User.query.get(cred.user_id)
                if not user:
                    log_task(f"\n--- Skipping credential {cred.id}: user not found ---")
                    continue

                log_task(f"\n--- Processing user {user.id}: {user.username} ---")

                # Get current active listings from eBay
                log_task(f"  Fetching active listings from eBay...")
                snapshot = fetch_active_listings_snapshot(user.id)

                if not snapshot.get('success'):
                    log_task(f"  ✗ Failed to fetch eBay inventory: {snapshot.get('error')}")
                    continue

                ebay_items = snapshot.get('offers', [])
                can_mark_inactive = snapshot.get('can_mark_inactive', False)
                sources = ', '.join(snapshot.get('sources', [])) or 'unknown'
                log_task(
                    f"  Found {len(ebay_items)} active listings on eBay "
                    f"(sources: {sources}, can_mark_inactive={can_mark_inactive})"
                )

                # Get all active items in our database for this user
                db_items = Item.query.filter_by(
                    user_id=user.id,
                    is_active=True
                ).filter(
                    Item.ebay_listing_id.isnot(None),
                    Item.ebay_listing_id != ''
                ).all()

                log_task(f"  Database has {len(db_items)} active items with eBay listing IDs")

                # Create a set of active eBay listing IDs for fast lookup
                active_ebay_listing_ids = set()
                for ebay_item in ebay_items:
                    listing_id = (
                        ebay_item.get('ebay_listing_id')
                        or ebay_item.get('listingId')
                        or ebay_item.get('listing_id')
                    )
                    if listing_id:
                        active_ebay_listing_ids.add(str(listing_id))

                if not ebay_items and db_items:
                    log_task("  ⚠ No active listings returned from eBay; skipping inactive marking")
                    db.session.commit()
                    users_processed += 1
                    continue

                if not can_mark_inactive:
                    log_task("  ⚠ Incomplete listing snapshot; skipping inactive marking")
                    db.session.commit()
                    users_processed += 1
                    continue

                db_listing_ids = {str(item.ebay_listing_id) for item in db_items if item.ebay_listing_id}
                overlap_count = len(active_ebay_listing_ids.intersection(db_listing_ids))
                if db_listing_ids and active_ebay_listing_ids and overlap_count == 0:
                    log_task(
                        "  ⚠ No overlap between eBay listings and DB listings; "
                        "skipping inactive marking to avoid mass deactivation"
                    )
                    db.session.commit()
                    users_processed += 1
                    continue

                # Check each database item against eBay
                marked_inactive = 0
                for db_item in db_items:
                    if str(db_item.ebay_listing_id) not in active_ebay_listing_ids:
                        # Item no longer active on eBay
                        db_item.is_active = False
                        try:
                            from qventory.helpers.link_bio import remove_featured_items_for_user
                            remove_featured_items_for_user(user.id, [db_item.id])
                        except Exception:
                            pass
                        log_task(f"    ⊗ Marked inactive: {db_item.sku} (eBay ID: {db_item.ebay_listing_id})")
                        marked_inactive += 1
                        total_marked_inactive += 1

                # Commit changes for this user
                db.session.commit()
                log_task(f"  ✓ User {user.username}: {marked_inactive} items marked as inactive")

                total_synced += len(ebay_items)
                users_processed += 1

            except Exception as e:
                log_task(f"  ✗ Error processing user {user.id}: {str(e)}")
                import traceback
                log_task(f"  Traceback: {traceback.format_exc()}")
                db.session.rollback()
                continue

        log_task(f"\n=== Sync and purge complete ===")
        log_task(f"Users processed: {users_processed}/{len(credentials)}")
        log_task(f"Total eBay items synced: {total_synced}")
        log_task(f"Total items marked inactive: {total_marked_inactive}")

        return {
            'success': True,
            'users_processed': users_processed,
            'total_users': len(credentials),
            'items_synced': total_synced,
            'items_marked_inactive': total_marked_inactive,
            'items_purged': total_purged
        }


@celery.task(bind=True, name='qventory.tasks.reactivate_inactive_ebay_items')
def reactivate_inactive_ebay_items(self):
    """
    Admin task: Reactivate items marked inactive but still active on eBay.

    Checks all active eBay credentials and reactivates items whose listing IDs or
    SKUs are present in the current active listing snapshot.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.item import Item
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User
        from qventory.helpers.ebay_inventory import fetch_active_listings_snapshot

        log_task("=== ADMIN: Reactivating inactive eBay items ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        total_accounts = len(credentials)
        log_task(f"Found {total_accounts} active eBay credentials to process")

        summary = []
        total_reactivated = 0

        for idx, credential in enumerate(credentials, start=1):
            user = credential.owner or User.query.get(credential.user_id)
            if not user:
                log_task(f"[{idx}/{total_accounts}] Skipping credential {credential.id}: user not found")
                continue

            log_task(f"[{idx}/{total_accounts}] Checking user {user.username} (ID {user.id})")

            snapshot = fetch_active_listings_snapshot(user.id)
            if not snapshot['success']:
                log_task(f"  ✗ Failed to fetch eBay snapshot: {snapshot.get('error')}")
                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'reactivated': 0,
                    'error': snapshot.get('error')
                })
                continue

            offers = snapshot.get('offers', [])
            offers_by_listing = {
                str(offer.get('ebay_listing_id')): offer
                for offer in offers
                if offer.get('ebay_listing_id')
            }

            inactive_items = Item.query.filter(
                Item.user_id == user.id,
                Item.is_active.is_(False),
                Item.ebay_listing_id.isnot(None)
            ).all()

            reactivated = 0
            for item in inactive_items:
                offer_data = None
                if item.ebay_listing_id:
                    offer_data = offers_by_listing.get(str(item.ebay_listing_id))

                if offer_data:
                    listing_id = offer_data.get('ebay_listing_id')
                    if listing_id:
                        existing = Item.query.filter(
                            Item.user_id == user.id,
                            Item.ebay_listing_id == str(listing_id),
                            Item.id != item.id
                        ).first()
                        if existing:
                            log_task(
                                f"  ⚠️  Skipping reactivation for item {item.id}: "
                                f"listing_id {listing_id} already belongs to item {existing.id}"
                            )
                            continue
                    item.is_active = True
                    item.synced_from_ebay = True
                    item.last_ebay_sync = datetime.utcnow()
                    if offer_data.get('item_price'):
                        item.item_price = offer_data['item_price']
                    if offer_data.get('ebay_url') and not item.ebay_url:
                        item.ebay_url = offer_data['ebay_url']
                    if not item.ebay_listing_id and listing_id:
                        item.ebay_listing_id = listing_id
                    if not item.ebay_sku and offer_data.get('ebay_sku'):
                        item.ebay_sku = offer_data['ebay_sku']
                    reactivated += 1

            if reactivated:
                db.session.commit()
                total_reactivated += reactivated
                log_task(f"  ✓ Reactivated {reactivated} items")
            else:
                log_task("  No items to reactivate")

            summary.append({
                'user_id': user.id,
                'username': user.username,
                'reactivated': reactivated
            })

            if hasattr(self, 'request') and self.request.id:
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': idx,
                        'total': total_accounts,
                        'last_user': user.username,
                        'total_reactivated': total_reactivated
                    }
                )

        log_task("=== Reactivation sweep finished ===")
        log_task(f"Total items reactivated: {total_reactivated}")

        return {
            'success': True,
            'accounts_found': total_accounts,
            'total_reactivated': total_reactivated,
            'results': summary
        }


@celery.task(bind=True, name='qventory.tasks.refresh_ebay_user_ids_global')
def refresh_ebay_user_ids_global(self):
    """
    Admin task: Refresh eBay tokens and re-fetch ebay_user_id for all active accounts.

    NOTE: Accounts with invalid refresh tokens still require manual reconnection.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.routes.ebay_auth import refresh_access_token, get_ebay_user_profile
        from datetime import datetime, timedelta

        log_task("=== ADMIN: Refreshing eBay user IDs ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        processed = 0
        refreshed = 0
        user_ids_updated = 0
        refresh_failed = 0
        user_id_missing = 0

        for cred in credentials:
            try:
                processed += 1
                refresh_token = cred.get_refresh_token()
                if not refresh_token:
                    refresh_failed += 1
                    cred.error_message = "missing_refresh_token"
                    continue

                token_data = refresh_access_token(refresh_token)
                cred.set_access_token(token_data['access_token'])
                if token_data.get('refresh_token'):
                    cred.set_refresh_token(token_data['refresh_token'])
                cred.token_expires_at = datetime.utcnow() + timedelta(
                    seconds=token_data.get('expires_in', 7200)
                )
                refreshed += 1

                profile = get_ebay_user_profile(token_data['access_token'])
                ebay_user_id = profile.get('username')
                ebay_top_rated = profile.get('top_rated')
                if ebay_user_id:
                    cred.ebay_user_id = ebay_user_id
                    user_ids_updated += 1
                else:
                    user_id_missing += 1
                    cred.error_message = "ebay_user_id_unresolved"
                if ebay_top_rated is not None:
                    cred.ebay_top_rated = ebay_top_rated

                cred.last_synced_at = datetime.utcnow()
                cred.sync_status = 'success'
                db.session.commit()

            except Exception as exc:
                refresh_failed += 1
                cred.sync_status = 'error'
                cred.error_message = f"refresh_failed: {exc}"
                db.session.rollback()
                continue

        log_task(
            "=== Refresh complete: "
            f"processed={processed} refreshed={refreshed} "
            f"user_ids_updated={user_ids_updated} refresh_failed={refresh_failed} "
            f"user_id_missing={user_id_missing} ==="
        )

        return {
            'success': True,
            'processed': processed,
            'refreshed': refreshed,
            'user_ids_updated': user_ids_updated,
            'refresh_failed': refresh_failed,
            'user_id_missing': user_id_missing
        }


def purge_duplicate_items_for_user(user_id):
    """
    Remove duplicate synced items for a specific user.

    Duplicates are identified via repeated eBay listing IDs to avoid deleting
    legitimately duplicated manual entries.
    """
    from qventory.models.item import Item
    from qventory.helpers.image_processor import delete_cloudinary_image

    duplicate_listing_ids = (
        db.session.query(Item.ebay_listing_id)
        .filter(
            Item.user_id == user_id,
            Item.synced_from_ebay.is_(True),
            Item.ebay_listing_id.isnot(None),
            Item.ebay_listing_id != ''
        )
        .group_by(Item.ebay_listing_id)
        .having(func.count(Item.id) > 1)
        .all()
    )

    purged_items = 0
    duplicate_groups = 0

    for (listing_id,) in duplicate_listing_ids:
        items = Item.query.filter_by(
            user_id=user_id,
            ebay_listing_id=listing_id
        ).order_by(
            Item.updated_at.desc(),
            Item.id.desc()
        ).all()

        if not items:
            continue

        duplicate_groups += 1

        # Keep the most recently updated record and delete the rest
        for duplicate in items[1:]:
            if duplicate.item_thumb:
                try:
                    delete_cloudinary_image(duplicate.item_thumb)
                except Exception as cleanup_error:
                    log_task(f"WARNING: Failed to remove Cloudinary image for item {duplicate.id}: {cleanup_error}")
            db.session.delete(duplicate)
            purged_items += 1

    if purged_items:
        db.session.commit()

    return purged_items, duplicate_groups


@celery.task(bind=True, name='qventory.tasks.resync_all_inventories_and_purge')
def resync_all_inventories_and_purge(self):
    """
    Admin task: purge duplicated eBay listings per account and resync every inventory.

    Runs a sync_all import per user so that existing listings are updated even if
    they already exist in Qventory.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User
        from qventory.models.item import Item

        log_task("=== ADMIN: Starting full inventory resync & dedup task ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        total_accounts = len(credentials)
        log_task(f"Found {total_accounts} active eBay credentials to process")

        summary = []
        total_purged = 0
        total_listing_dates = 0

        for idx, credential in enumerate(credentials, start=1):
            user = credential.owner or User.query.get(credential.user_id)
            if not user:
                log_task(f"[{idx}/{total_accounts}] Skipping credential {credential.id}: user not found")
                continue

            log_task(f"[{idx}/{total_accounts}] Processing user {user.username} (ID {user.id})")

            purged_items = 0
            duplicate_groups = 0
            try:
                purged_items, duplicate_groups = purge_duplicate_items_for_user(user.id)
                total_purged += purged_items
                if purged_items:
                    log_task(f"  ✓ Removed {purged_items} duplicate items ({duplicate_groups} listing IDs)")
                else:
                    log_task("  No duplicate listings detected for this account")
            except Exception as purge_error:
                db.session.rollback()
                log_task(f"  ✗ Error removing duplicates for user {user.username}: {purge_error}")
                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'purged': 0,
                    'error': f"purge_failed: {purge_error}"
                })
                continue

            try:
                import_result = import_ebay_inventory.run(
                    user.id,
                    import_mode='sync_all',
                    listing_status='ACTIVE'
                )
                listing_dates_updated = 0
                try:
                    from qventory.helpers.ebay_inventory import get_listing_time_details
                    items_with_listings = Item.query.filter(
                        Item.user_id == user.id,
                        Item.ebay_listing_id.isnot(None)
                    ).all()
                    for idx_item, item in enumerate(items_with_listings, start=1):
                        if item.listing_date:
                            continue
                        listing_times = get_listing_time_details(user.id, item.ebay_listing_id)
                        start_time = listing_times.get('start_time')
                        if start_time:
                            item.listing_date = start_time.date()
                            listing_dates_updated += 1
                        if idx_item % 50 == 0:
                            db.session.commit()
                    if listing_dates_updated:
                        db.session.commit()
                        total_listing_dates += listing_dates_updated
                        log_task(f"  ✓ Backfilled {listing_dates_updated} listing dates")
                except Exception as listing_date_error:
                    db.session.rollback()
                    log_task(f"  ✗ Error backfilling listing dates for user {user.username}: {listing_date_error}")
                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'purged': purged_items,
                    'imported': import_result.get('imported', 0),
                    'updated': import_result.get('updated', 0),
                    'listing_dates': listing_dates_updated,
                    'skipped': import_result.get('skipped', 0)
                })
                log_task(f"  ✓ Resync complete: {import_result.get('imported', 0)} imported / {import_result.get('updated', 0)} updated")
            except Exception as import_error:
                db.session.rollback()
                log_task(f"  ✗ Error resyncing inventory for user {user.username}: {import_error}")
                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'purged': purged_items,
                    'error': f"import_failed: {import_error}"
                })

            if hasattr(self, 'request') and self.request.id:
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': idx,
                        'total': total_accounts,
                        'last_user': user.username,
                        'total_purged': total_purged
                    }
                )

        log_task("=== Full inventory resync finished ===")
        log_task(f"Total duplicates purged: {total_purged}")
        log_task(f"Accounts processed: {len(summary)}/{total_accounts}")

        return {
            'success': True,
            'accounts_found': total_accounts,
            'accounts_processed': len(summary),
            'total_duplicates_removed': total_purged,
            'results': summary
        }


@celery.task(bind=True, name='qventory.tasks.resync_all_inventories_backfill_dates')
def resync_all_inventories_backfill_dates(self):
    """
    Admin task: resync every eBay inventory and backfill listing_date from eBay.

    NOTE: This does NOT deduplicate listings.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.user import User
        from qventory.models.item import Item

        log_task("=== ADMIN: Starting resync + backfill listing dates (no dedup) ===")
        credentials = MarketplaceCredential.query.filter_by(
            marketplace='ebay',
            is_active=True
        ).all()

        total_accounts = len(credentials)
        log_task(f"Found {total_accounts} active eBay credentials to process")

        summary = []
        total_listing_dates = 0

        for idx, credential in enumerate(credentials, start=1):
            user = credential.owner or User.query.get(credential.user_id)
            if not user:
                log_task(f"[{idx}/{total_accounts}] Skipping credential {credential.id}: user not found")
                continue

            log_task(f"[{idx}/{total_accounts}] Processing user {user.username} (ID {user.id})")

            try:
                import_result = import_ebay_inventory.run(
                    user.id,
                    import_mode='sync_all',
                    listing_status='ACTIVE'
                )

                listing_dates_updated = 0
                try:
                    from qventory.helpers.ebay_inventory import get_listing_time_details
                    items_with_listings = Item.query.filter(
                        Item.user_id == user.id,
                        Item.ebay_listing_id.isnot(None)
                    ).all()
                    for idx_item, item in enumerate(items_with_listings, start=1):
                        if item.listing_date:
                            continue
                        listing_times = get_listing_time_details(user.id, item.ebay_listing_id)
                        start_time = listing_times.get('start_time')
                        if start_time:
                            item.listing_date = start_time.date()
                            listing_dates_updated += 1
                        if idx_item % 50 == 0:
                            db.session.commit()
                    if listing_dates_updated:
                        db.session.commit()
                        total_listing_dates += listing_dates_updated
                        log_task(f"  ✓ Backfilled {listing_dates_updated} listing dates")
                except Exception as listing_date_error:
                    db.session.rollback()
                    log_task(f"  ✗ Error backfilling listing dates for user {user.username}: {listing_date_error}")

                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'imported': import_result.get('imported', 0),
                    'updated': import_result.get('updated', 0),
                    'listing_dates': listing_dates_updated,
                    'skipped': import_result.get('skipped', 0)
                })
                log_task(f"  ✓ Resync complete: {import_result.get('imported', 0)} imported / {import_result.get('updated', 0)} updated")
            except Exception as import_error:
                db.session.rollback()
                log_task(f"  ✗ Error resyncing inventory for user {user.username}: {import_error}")
                summary.append({
                    'user_id': user.id,
                    'username': user.username,
                    'error': f"import_failed: {import_error}"
                })

            if hasattr(self, 'request') and self.request.id:
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': idx,
                        'total': total_accounts,
                        'last_user': user.username,
                        'total_listing_dates': total_listing_dates
                    }
                )

        log_task("=== Resync + backfill listing dates finished ===")
        log_task(f"Accounts processed: {len(summary)}/{total_accounts}")
        log_task(f"Listing dates backfilled: {total_listing_dates}")

        return {
            'success': True,
            'accounts_found': total_accounts,
            'accounts_processed': len(summary),
            'total_listing_dates': total_listing_dates,
            'results': summary
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_category_fee_catalog')
def sync_ebay_category_fee_catalog(self, user_id=None, marketplace_id="EBAY_US", force=False):
    """
    Master task: sync eBay category tree and enqueue fee sync chunks.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.system_setting import SystemSetting
        from qventory.models.marketplace_credential import MarketplaceCredential
        from qventory.models.ebay_category import EbayCategory
        from qventory.helpers.ebay_taxonomy import sync_ebay_categories

        now = datetime.utcnow()
        last_setting = SystemSetting.query.filter_by(key='ebay_category_fee_last_sync').first()
        if last_setting and last_setting.value_int and not force:
            if (now.timestamp() - last_setting.value_int) < (30 * 24 * 3600):
                return {"success": True, "skipped": "recent_sync"}

        if not user_id:
            cred = MarketplaceCredential.query.filter_by(
                marketplace='ebay',
                is_active=True
            ).order_by(MarketplaceCredential.updated_at.desc()).first()
            if cred:
                user_id = cred.user_id

        if not user_id:
            return {"success": False, "error": "No active eBay credential available for fee sync"}

        sync_result = sync_ebay_categories(marketplace_id=marketplace_id)

        total_leaf = EbayCategory.query.filter(EbayCategory.is_leaf.is_(True)).count()
        if total_leaf == 0:
            return {"success": False, "error": "No eBay categories found after sync"}

        chunk_size = 200
        queued = 0
        for offset in range(0, total_leaf, chunk_size):
            sync_ebay_category_fee_catalog_chunk.delay(
                user_id=user_id,
                offset=offset,
                limit=chunk_size,
                marketplace_id=marketplace_id
            )
            queued += 1

        if not last_setting:
            last_setting = SystemSetting(key='ebay_category_fee_last_sync')
            db.session.add(last_setting)
        last_setting.value_int = int(now.timestamp())
        db.session.commit()

        return {
            "success": True,
            "categories_synced": sync_result.get("total"),
            "leaf_categories": total_leaf,
            "chunks_queued": queued
        }


@celery.task(bind=True, name='qventory.tasks.sync_ebay_category_fee_catalog_chunk')
def sync_ebay_category_fee_catalog_chunk(self, user_id, offset, limit, marketplace_id="EBAY_US"):
    """
    Chunk task: fetch live fee estimates for a slice of leaf categories and store in EbayFeeRule.
    """
    app = create_app()

    with app.app_context():
        from qventory.models.ebay_category import EbayCategory
        from qventory.models.ebay_fee_rule import EbayFeeRule
        from qventory.helpers.ebay_fee_live import get_live_fee_estimate
        from qventory.models.system_setting import SystemSetting

        base_price = float(SystemSetting.get_int('ebay_fee_sync_base_price', 100) or 100)
        base_shipping = float(SystemSetting.get_int('ebay_fee_sync_base_shipping', 10) or 10)

        categories = (
            EbayCategory.query.filter(EbayCategory.is_leaf.is_(True))
            .order_by(EbayCategory.category_id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        updated = 0
        created = 0
        errors = 0

        for idx, cat in enumerate(categories, start=1):
            try:
                live = get_live_fee_estimate(
                    user_id=user_id,
                    category_id=cat.category_id,
                    price=base_price,
                    shipping_cost=base_shipping,
                    has_store=False,
                    top_rated=False
                )
                if not live.get("success"):
                    errors += 1
                    continue

                rate = float(live.get("fee_rate_percent") or 0)
                if rate <= 0:
                    errors += 1
                    continue

                fixed_fee = 0.30
                for fee in live.get("fees") or []:
                    name = (fee.get("name") or "").lower()
                    if "fixed" in name and fee.get("amount") is not None:
                        try:
                            fixed_fee = float(fee.get("amount"))
                        except (TypeError, ValueError):
                            fixed_fee = 0.30
                        break

                rule = EbayFeeRule.query.filter_by(category_id=cat.category_id).first()
                if rule:
                    rule.standard_rate = rate
                    rule.fixed_fee = fixed_fee
                    rule.updated_at = datetime.utcnow()
                    updated += 1
                else:
                    rule = EbayFeeRule(
                        category_id=cat.category_id,
                        standard_rate=rate,
                        store_rate=None,
                        top_rated_discount=10.0,
                        fixed_fee=fixed_fee
                    )
                    db.session.add(rule)
                    created += 1

                if idx % 25 == 0:
                    db.session.commit()

                time.sleep(0.5)
            except Exception:
                db.session.rollback()
                errors += 1

        db.session.commit()

        return {
            "success": True,
            "offset": offset,
            "limit": limit,
            "processed": len(categories),
            "created": created,
            "updated": updated,
            "errors": errors
        }
