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

                    if ebay_sku:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            ebay_sku=ebay_sku
                        ).first()

                    if not existing_item and ebay_title:
                        existing_item = Item.query.filter_by(
                            user_id=user_id,
                            title=ebay_title
                        ).first()

                    if existing_item:
                        log_task(f"  Item exists (ID: {existing_item.id})")

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
                            log_task(f"  → Updated")
                        else:
                            skipped_count += 1
                            log_task(f"  → Skipped")
                    else:
                        log_task(f"  New item")

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
                            log_task(f"  → Created (SKU: {new_sku})")
                        else:
                            skipped_count += 1
                            log_task(f"  → Skipped")

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
